from __future__ import annotations

from pixiv_yuri.jjwxc.ranking_collector import parse_ranking_page


def test_ranking_parser_keeps_metadata_and_discards_synopsis_attribute() -> None:
    html = """
    <html><body><table>
      <tr><td>序号</td><td>作者</td><td>作品</td></tr>
      <tr>
        <td>1</td>
        <td><a href="oneauthor.php?authorid=700001">南汀</a></td>
        <td><a href="onebook.php?novelid=90000001" rel="不应保存的文案原文">向晚潮声</a></td>
        <td>原创-百合-近代现代-爱情</td><td>连载</td><td>182,400</td>
        <td><div>164,800,000</div></td><td>2026-06-04 20:00:00</td>
      </tr>
    </table></body></html>
    """.encode("gb18030")

    entries = parse_ranking_page(html)

    assert len(entries) == 1
    assert entries[0].novel_id == "90000001"
    assert entries[0].author_id == "700001"
    assert entries[0].word_count == 182_400
    assert entries[0].points == 164_800_000
    assert "文案" not in entries[0].model_dump_json()


def test_ranking_parser_rejects_non_contiguous_positions() -> None:
    html = """
    <table><tr><td>2</td>
      <td><a href="oneauthor.php?authorid=1">作者</a></td>
      <td><a href="onebook.php?novelid=2">作品</a></td>
      <td>原创-百合-近代现代-爱情</td><td>完结</td><td>1</td><td>2</td>
      <td>2026-06-04 20:00:00</td></tr></table>
    """.encode("gb18030")

    try:
        parse_ranking_page(html)
    except ValueError as error:
        assert str(error) == "ranking_order_invalid"
    else:
        raise AssertionError("non-contiguous ranking should be rejected")
