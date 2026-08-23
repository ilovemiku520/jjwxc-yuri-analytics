from __future__ import annotations

import gzip
from datetime import UTC, datetime

import pytest

from pixiv_yuri.jjwxc import public_probe
from pixiv_yuri.jjwxc.html_parser import JjwxcParseError, decode_jjwxc_html, parse_novel_page


def _page() -> bytes:
    html = """
    <html><head><meta charset="gb18030"><title>《合成测试小说》</title></head>
    <body>
      <a href="oneauthor.php?authorid=7654321">作者专栏</a>
      <h1>《合成测试小说》</h1><p>作者：合成作者</p>
      <ul><li>文章类型：原创-百合-近代现代-爱情</li>
      <li>作品视角：互攻</li><li>文章进度：连载</li><li>全文字数：123,456字</li></ul>
      <div id="novelintro">这是一个都市成长故事。两位主角彼此救赎！</div>
      <p>内容标签： 都市 情有独钟 HE 主角：合成人物</p>
      <p>非V章节章均点击数：12,345 总书评数：321 当前被收藏数：4,567
      营养液数：0 文章积分：89,012,345</p>
      <article>这里是不能进入候选数据的章节正文</article>
    </body></html>
    """
    return html.encode("gb18030")


def test_parser_extracts_only_minimized_public_aggregates() -> None:
    candidate = parse_novel_page(
        _page(),
        novel_id="10806685",
        observed_at=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert candidate.novel_id == "10806685"
    assert candidate.author_id == "7654321"
    assert candidate.title == "合成测试小说"
    assert candidate.novel_type == "原创-百合-近代现代-爱情"
    assert candidate.perspective == "互攻"
    assert candidate.status == "连载"
    assert candidate.word_count == 123_456
    assert candidate.review_count == 321
    assert candidate.favorite_count == 4_567
    assert candidate.points == 89_012_345
    assert candidate.average_non_v_chapter_click_count == 12_345
    assert candidate.synopsis_char_count == 20
    assert candidate.synopsis_sentence_count == 2
    assert candidate.synopsis_theme_terms == ("成长", "救赎", "都市")
    assert candidate.tags == ("都市", "情有独钟", "HE")
    assert "正文" not in candidate.model_dump_json()
    assert "两位主角" not in candidate.model_dump_json()


def test_parser_preserves_missing_click_as_unknown() -> None:
    payload = _page().replace("12,345".encode("gb18030"), b"")
    candidate = parse_novel_page(
        payload,
        novel_id="10806685",
        observed_at=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert candidate.average_non_v_chapter_click_count is None


def test_decoder_rejects_oversize_or_unexpected_charset() -> None:
    with pytest.raises(JjwxcParseError, match="html_size_outside_boundary"):
        decode_jjwxc_html(b"")
    with pytest.raises(JjwxcParseError, match="html_charset_not_allowed"):
        decode_jjwxc_html(b'<meta charset="shift_jis">payload')


def test_parser_rejects_missing_required_counts() -> None:
    payload = '<meta charset="utf-8"><h1>《不完整》</h1>'.encode()
    with pytest.raises(JjwxcParseError):
        parse_novel_page(
            payload,
            novel_id="1",
            observed_at=datetime(2026, 8, 23, tzinfo=UTC),
        )


def test_live_probe_accepts_bounded_gzip_without_persisting_raw_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Headers:
        def get_content_type(self) -> str:
            return "text/html"

        def get(self, name: str, default: str = "") -> str:
            return "gzip" if name == "Content-Encoding" else default

    class Response:
        status = 200
        headers = Headers()

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return "https://www.jjwxc.net/onebook.php?novelid=10806685"

        def read(self, size: int) -> bytes:
            assert size > 0
            return gzip.compress(_page())

    class Opener:
        def open(self, request: object, timeout: float) -> Response:
            assert request is not None
            assert timeout == 20.0
            return Response()

    monkeypatch.setenv("JJYURI_ENABLE_NETWORK", "true")
    monkeypatch.setattr(public_probe.urllib.request, "build_opener", lambda *args: Opener())
    result = public_probe.probe_public_novel("10806685")

    assert result["status"] == "candidate_ready"
    assert result["boundary"]["raw_payload_persisted"] is False
