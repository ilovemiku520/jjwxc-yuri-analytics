from __future__ import annotations

from datetime import UTC, datetime

from pixiv_yuri.jjwxc.catalog_parser import (
    enrich_candidate_with_chapters,
    parse_channel_catalog,
    parse_chapter_click_payload,
    parse_chapter_directory,
)
from pixiv_yuri.jjwxc.html_parser import parse_novel_page


def test_channel_parser_extracts_both_named_lists_and_discovery_union() -> None:
    payload = """
    <meta charset="gb18030"><div id="bangdan10">
      <ul class="bdhe_lef_tit"><li>频道金榜</li><li>新手金榜</li></ul>
      <ul class="bdhe_lef_bod">
        <li><a data-recommendInfo='{"rankid":1067}' title="金榜作品"
          href="//www.jjwxc.net/onebook.php?novelid=101">短标题</a></li>
      </ul>
      <ul class="bdhe_lef_bod" style="display:none">
        <li><a data-recommendInfo='{"rankid":1068}' title="新手作品"
          href="//www.jjwxc.net/onebook.php?novelid=202">新手作品</a></li>
      </ul>
    </div>
    <a href="//www.jjwxc.net/onebook.php?novelid=303">频道推荐</a>
    """.encode("gb18030")

    catalog = parse_channel_catalog(payload)

    assert [item.novel_id for item in catalog.rankings["channel_gold"]] == ["101"]
    assert catalog.rankings["channel_gold"][0].title == "金榜作品"
    assert catalog.rankings["newcomer"][0].source_rank_id == "1068"
    assert catalog.discovered_novel_ids == ("101", "202", "303")


def test_chapter_parser_keeps_clicks_and_vip_boundary_without_prose() -> None:
    page = """
    <meta charset="gb18030"><table>
      <tr itemprop="chapter"><td>1</td><td><a
        href="onebook.php?novelid=88&chapterid=1">第一章</a></td>
        <td>不能保留的内容提要</td><td itemprop="wordCount">3,200</td>
        <td class="chapterclick" clickchapterid="1"></td></tr>
      <tr itemprop="chapter"><td>2</td><td><a id="vip_2"
        rel="https://my.jjwxc.net/onebook_vip.php?novelid=88&chapterid=2">第二章</a>
        <font>[VIP]</font></td><td>也不能保留</td><td itemprop="wordCount">4,100</td>
        <td></td></tr>
    </table>
    """.encode("gb18030")
    clicks = b'novelclick({"1":"500","2":"300"})'

    chapters = parse_chapter_directory(page, click_payload=clicks)

    assert [(item.chapter_id, item.is_vip, item.click_count) for item in chapters] == [
        (1, False, 500),
        (2, True, 300),
    ]
    assert chapters[0].word_count == 3_200
    assert "内容提要" not in chapters[0].model_dump_json()


def test_chapter_parser_deduplicates_identical_desktop_directory_rendering() -> None:
    row = """
      <tr itemprop="chapter"><td>1</td><td>
      <a href="onebook.php?novelid=88&chapterid=1">第一章</a></td>
      <td>摘要</td><td itemprop="wordCount">3,200</td>
      <td class="chapterclick" clickchapterid="1"></td></tr>
    """
    page = f'<meta charset="gb18030"><table>{row}{row}</table>'.encode("gb18030")

    chapters = parse_chapter_directory(page, click_payload=b'novelclick({"1":"500"})')

    assert len(chapters) == 1
    assert chapters[0].click_count == 500


def test_chapter_parser_recovers_unique_position_from_stale_long_directory_link() -> None:
    page = """
    <meta charset="gb18030"><table>
      <tr itemprop="chapter"><td>166</td><td><a
      href="onebook.php?novelid=88&chapterid=166">166</a></td>
      <td>摘要</td><td itemprop="wordCount">3,200</td><td></td></tr>
      <tr itemprop="chapter"><td>167</td><td><a
      href="onebook.php?novelid=88&chapterid=166">167</a></td>
      <td>摘要</td><td itemprop="wordCount">2,800</td><td></td></tr>
    </table>
    """.encode("gb18030")

    chapters = parse_chapter_directory(page)

    assert [item.chapter_id for item in chapters] == [166, 167]
    assert [item.position for item in chapters] == [166, 167]


def test_click_jsonp_and_candidate_aggregates_distinguish_missing_vip_clicks() -> None:
    payload = """
    <meta charset="gb18030"><h1>《测试》</h1>
    <a href="oneauthor.php?authorid=7">作者专栏</a><p>作者：作者甲</p>
    <p>文章类型：原创-百合-近代现代-爱情 作品视角：互攻 文章进度：连载
    全文字数：7,300字</p><div id="novelintro">都市成长。</div>
    <p>内容标签： 都市 HE 主角：甲 总书评数：10 当前被收藏数：20 文章积分：30</p>
    <table>
      <tr itemprop="chapter"><td>1</td><td>
      <a href="onebook.php?novelid=88&chapterid=1">1</a></td>
      <td>摘要</td><td itemprop="wordCount">3200</td>
      <td class="chapterclick" clickchapterid="1"></td></tr>
      <tr itemprop="chapter"><td>2</td><td><a id="vip_2"
      rel="onebook_vip.php?novelid=88&chapterid=2">2</a></td>
      <td>摘要</td><td itemprop="wordCount">4100</td><td></td></tr>
    </table>
    """.encode("gb18030")
    click_payload = b'novelclick({"1":"500"})'
    candidate = parse_novel_page(
        payload,
        novel_id="88",
        observed_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    chapters = parse_chapter_directory(payload, click_payload=click_payload)

    enriched = enrich_candidate_with_chapters(candidate, chapters)

    assert parse_chapter_click_payload(click_payload) == {1: 500}
    assert enriched.average_non_v_chapter_click_count == 500
    assert enriched.average_v_chapter_click_count is None
    assert enriched.non_v_chapter_count == 1
    assert enriched.v_chapter_count == 1
    assert enriched.chapter_click_coverage_count == 1
