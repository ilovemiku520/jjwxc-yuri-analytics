"""Minimized parser for a public JJWXC novel overview page."""

from __future__ import annotations

import html as html_module
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Literal

from pixiv_yuri.jjwxc.models import JjwxcNovelCandidate

MAX_HTML_BYTES = 750_000
_META_CHARSET = re.compile(rb"charset\s*=\s*['\"]?([A-Za-z0-9_-]+)", re.IGNORECASE)
_ALLOWED_CHARSETS = {"utf-8", "utf8", "gb18030", "gbk", "gb2312"}
_SYNOPSIS_THEME_TERMS = (
    "成长",
    "救赎",
    "校园",
    "都市",
    "悬疑",
    "科幻",
    "历史",
    "职场",
    "冒险",
    "重生",
    "穿越",
    "破镜重圆",
)
_VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class JjwxcParseError(ValueError):
    """Raised when a public page does not match the minimized contract."""


def decode_jjwxc_html(payload: bytes) -> str:
    """Decode a bounded response using only expected JJWXC encodings."""
    if not payload or len(payload) > MAX_HTML_BYTES:
        raise JjwxcParseError("html_size_outside_boundary")
    charset_match = _META_CHARSET.search(payload[:8_192])
    charset = charset_match.group(1).decode("ascii").lower() if charset_match else "gb18030"
    if charset not in _ALLOWED_CHARSETS:
        raise JjwxcParseError("html_charset_not_allowed")
    normalized = "utf-8" if charset in {"utf-8", "utf8"} else "gb18030"
    try:
        return payload.decode(normalized, errors="strict")
    except UnicodeDecodeError as exc:
        raise JjwxcParseError("html_decode_failed") from exc


def parse_novel_page(
    payload: bytes,
    *,
    novel_id: str,
    observed_at: datetime,
) -> JjwxcNovelCandidate:
    """Extract only public aggregate metadata; discard page text after parsing."""
    if not re.fullmatch(r"[1-9][0-9]{0,11}", novel_id):
        raise JjwxcParseError("novel_id_invalid")
    source = decode_jjwxc_html(payload)
    synopsis = _extract_synopsis_text(source)
    author_match = re.search(r"oneauthor\.php\?authorid=([1-9][0-9]{0,11})", source)
    text = _visible_text(source)
    title = _required(text, r"《([^》]{1,200})》", "title_missing")
    author_name = _required(text, r"作者[：:]\s*([^\s]{1,80})", "author_name_missing")
    novel_type = _required(
        text,
        r"文章类型[：:]\s*(.{1,100}?)(?=作品视角|所属系列|文章进度)",
        "novel_type_missing",
    )
    perspective = _optional(text, r"作品视角[：:]\s*([^\s]{1,30})")
    raw_status = _optional(text, r"文章进度[：:]\s*([^\s]{1,30})") or "未知"
    status: Literal["连载", "完结", "暂停", "锁定", "未知"] = "未知"
    if raw_status == "连载":
        status = "连载"
    elif raw_status == "完结":
        status = "完结"
    elif raw_status == "暂停":
        status = "暂停"
    elif raw_status == "锁定":
        status = "锁定"
    if author_match is None:
        raise JjwxcParseError("author_id_missing")
    return JjwxcNovelCandidate(
        novel_id=novel_id,
        title=title,
        author_id=author_match.group(1),
        author_display_name=author_name,
        novel_type=novel_type,
        perspective=perspective,
        status=status,
        word_count=_required_count(text, r"全文字数[：:]?\s*([0-9,]+)\s*字", "word_count_missing"),
        review_count=_required_count(text, r"总书评数[：:]\s*([0-9,]+)", "review_count_missing"),
        favorite_count=_required_count(
            text, r"当前被收藏数[：:]\s*([0-9,]+)", "favorite_count_missing"
        ),
        points=_required_count(text, r"文章积分[：:]\s*([0-9,]+)", "points_missing"),
        average_non_v_chapter_click_count=_optional_count(
            text, r"非\s*[vVＶ]\s*章节章均点击数[：:]?\s*([0-9,]+)"
        ),
        synopsis_char_count=_synopsis_char_count(synopsis),
        synopsis_sentence_count=_synopsis_sentence_count(synopsis),
        synopsis_theme_terms=_synopsis_theme_terms(synopsis),
        tags=_extract_tags(text),
        observed_at=observed_at,
        source_url=f"https://www.jjwxc.net/onebook.php?novelid={novel_id}",
    )


def _visible_text(source: str) -> str:
    without_active = re.sub(r"(?is)<(script|style).*?</\1>", " ", source)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_active)
    return re.sub(r"\s+", " ", html_module.unescape(without_tags)).strip()


def _required(text: str, pattern: str, error_code: str) -> str:
    value = _optional(text, pattern)
    if value is None:
        raise JjwxcParseError(error_code)
    return value


def _optional(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _required_count(text: str, pattern: str, error_code: str) -> int:
    value = _required(text, pattern, error_code)
    return int(value.replace(",", ""))


def _optional_count(text: str, pattern: str) -> int | None:
    value = _optional(text, pattern)
    return int(value.replace(",", "")) if value is not None else None


def _extract_tags(text: str) -> tuple[str, ...]:
    match = re.search(r"内容标签[：:]\s*(.{1,300}?)(?=主角|一句话简介|立意|文章基本信息)", text)
    if match is None:
        return ()
    tags: list[str] = []
    for item in match.group(1).split():
        normalized = item.strip("·、,，")
        if normalized and len(normalized) <= 40 and normalized not in tags:
            tags.append(normalized)
        if len(tags) == 20:
            break
    return tuple(tags)


class _NovelIntroExtractor(HTMLParser):
    """Collect a bounded intro node transiently; callers retain derived values only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._parts: list[str] = []
        self._char_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        intro_id = attr_map.get("id") or ""
        if self._depth == 0 and intro_id.casefold() == "novelintro":
            self._depth = 1
        elif self._depth > 0:
            if tag.casefold() == "br":
                self._parts.append("。")
                self._char_count += 1
            if tag.casefold() not in _VOID_HTML_TAGS:
                self._depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth > 0 and tag.casefold() == "br":
            self._parts.append("。")

    def handle_endtag(self, tag: str) -> None:
        if self._depth > 0:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth > 0 and self._char_count < 100_000:
            bounded = data[: 100_000 - self._char_count]
            self._parts.append(bounded)
            self._char_count += len(bounded)

    @property
    def text(self) -> str | None:
        value = re.sub(r"\s+", "", "".join(self._parts)).strip()
        return value[:100_000] if value else None


def _extract_synopsis_text(source: str) -> str | None:
    parser = _NovelIntroExtractor()
    parser.feed(source)
    parser.close()
    return parser.text


def _synopsis_char_count(synopsis: str | None) -> int | None:
    return len(synopsis) if synopsis is not None else None


def _synopsis_sentence_count(synopsis: str | None) -> int | None:
    if synopsis is None:
        return None
    segments = [item for item in re.split(r"[。！？!?…]+", synopsis) if item]
    return max(1, len(segments))


def _synopsis_theme_terms(synopsis: str | None) -> tuple[str, ...]:
    if synopsis is None:
        return ()
    return tuple(term for term in _SYNOPSIS_THEME_TERMS if term in synopsis)
