from __future__ import annotations

from datetime import UTC, datetime

from pixiv_yuri.jjwxc.catalog_parser import (
    enrich_candidate_with_aggregate,
    enrich_candidate_with_chapters,
    parse_author_profile,
    parse_bookbase_page,
    parse_channel_catalog,
    parse_chapter_click_payload,
    parse_chapter_directory,
    parse_novel_aggregate_payload,
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


def test_bookbase_parser_extracts_minimal_search_index_without_synopsis() -> None:
    payload = """
    <meta charset="gb18030">
    <p>共 <font color="red"> 2222</font> 页, 当前为第 <font color="red"> 7 </font>页</p>
    <table class="cytable"><tbody>
      <tr><td>作者</td><td>作品</td><td>类型</td><td>进度</td><td>字数</td><td>积分</td><td>发表时间</td></tr>
      <tr>
        <td><a href="oneauthor.php?authorid=71">作者甲</a></td>
        <td><a href="onebook.php?novelid=88" title="简介：不能入库">测试作品</a></td>
        <td>原创-百合-近代现代-爱情-互攻</td><td><font>完结</font></td>
        <td>123,456</td><td>8,765,432</td><td>2026-08-23 20:32:26</td>
      </tr>
    </tbody></table>
    """.encode("gb18030")

    page = parse_bookbase_page(payload)

    assert page.current_page == 7
    assert page.total_pages == 2222
    assert len(page.entries) == 1
    assert page.entries[0].novel_id == "88"
    assert page.entries[0].author_display_name == "作者甲"
    assert page.entries[0].word_count == 123_456
    assert page.entries[0].points == 8_765_432
    assert "不能入库" not in page.entries[0].model_dump_json()


def test_author_profile_parser_excludes_locked_works_and_profile_prose() -> None:
    payload = """
    <meta charset="gb18030"><div>被收藏数：12,345</div><p>不可保存的作者简介</p>
    <table><tr><td><table><tr><td><a href="onebook.php?novelid=81">作品甲</a></td></tr></table></td>
      <td>原创-百合</td><td>连载</td><td>100,000</td><td>8,000,000</td><td>2026</td></tr>
    <tr><td><a href="onebook.php?novelid=82" rel="本文章由作者自行锁定！">作*[锁]</a></td>
      <td>随笔</td><td>完结</td><td>50,000</td><td>2,000,000</td><td>2020</td></tr></table>
    """.encode("gb18030")

    profile = parse_author_profile(
        payload,
        author_id="71",
        observed_at=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert profile.author_favorite_count == 12_345
    assert profile.nonlocked_work_count == 1
    assert profile.locked_work_count == 1
    assert profile.total_word_count == 100_000
    assert profile.total_points == 8_000_000
    assert "作者简介" not in profile.model_dump_json()


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


def test_click_jsonp_preserves_authenticated_inline_vip_clicks() -> None:
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
      <td>摘要</td><td itemprop="wordCount">4100</td>
      <td class="chapterclick" clickchapterid="2">300</td></tr>
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
    assert enriched.first_chapter_click_count == 500
    assert enriched.average_v_chapter_click_count == 300
    assert enriched.non_v_chapter_count == 1
    assert enriched.v_chapter_count == 1
    assert enriched.chapter_click_coverage_count == 2
    assert enriched.v_to_non_v_click_retention_basis_points == 6_000
    assert enriched.first_click_to_favorite_basis_points == 250_000


def test_public_aggregate_jsonp_overlays_dynamic_nutrition_and_counters() -> None:
    aggregate = parse_novel_aggregate_payload(
        b'jjyuriAggregate({"collectedCount":"31,687","novelscore":"1,207,603,968",'
        b'"comment_count":"69479","nutritionCount":"83235"})'
    )
    candidate = parse_novel_page(
        """
        <meta charset="gb18030"><h1>《测试》</h1>
        <a href="oneauthor.php?authorid=7">作者专栏</a><p>作者：作者甲</p>
        <p>文章类型：原创-百合-近代现代-爱情 作品视角：互攻 文章进度：连载
        全文字数：7,300字</p><div id="novelintro">都市成长。</div>
        <p>内容标签： 都市 HE 主角：甲 总书评数：10 当前被收藏数：20
        营养液数： 文章积分：30</p>
        """.encode("gb18030"),
        novel_id="88",
        observed_at=datetime(2026, 8, 25, tzinfo=UTC),
    )

    enriched = enrich_candidate_with_aggregate(candidate, aggregate)

    assert enriched.favorite_count == 31_687
    assert enriched.review_count == 69_479
    assert enriched.nutrition_count == 83_235
    assert enriched.points == 1_207_603_968
    assert enriched.nutrition_to_favorite_basis_points == 26_268


def test_click_retention_proxy_preserves_missing_v_clicks() -> None:
    candidate = parse_novel_page(
        """
        <meta charset="gb18030"><h1>《测试》</h1>
        <a href="oneauthor.php?authorid=7">作者专栏</a><p>作者：作者甲</p>
        <p>文章类型：原创-百合-近代现代-爱情 作品视角：互攻 文章进度：连载
        全文字数：7,300字</p><div id="novelintro">都市成长。</div>
        <p>内容标签： 都市 HE 主角：甲 总书评数：10 当前被收藏数：20 文章积分：30</p>
        """.encode("gb18030"),
        novel_id="88",
        observed_at=datetime(2026, 8, 24, tzinfo=UTC),
    ).model_copy(update={"average_non_v_chapter_click_count": 500})

    assert candidate.v_to_non_v_click_retention_basis_points is None
