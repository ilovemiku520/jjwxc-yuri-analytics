"""Parsers for the yuri channel discovery lists and copyright-minimized chapter metrics."""

from __future__ import annotations

import html as html_module
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from pixiv_yuri.jjwxc.html_parser import JjwxcParseError, decode_jjwxc_html
from pixiv_yuri.jjwxc.models import JjwxcChapterMetric, JjwxcNovelCandidate

_MAX_CLICK_BYTES = 500_000
CHANNEL_RANKING_KEYS = ("channel_gold", "newcomer")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class JjwxcChannelRankingEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ranking_key: str = Field(pattern=r"^(channel_gold|newcomer)$")
    rank: int = Field(ge=1, le=100)
    novel_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    title: str = Field(min_length=1, max_length=200)
    source_rank_id: str | None = Field(default=None, pattern=r"^[0-9]{1,12}$")


class JjwxcChannelCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rankings: dict[str, tuple[JjwxcChannelRankingEntry, ...]]
    discovered_novel_ids: tuple[str, ...]


class JjwxcBookbaseEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    novel_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    title: str = Field(min_length=1, max_length=200)
    author_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    author_display_name: str = Field(min_length=1, max_length=80)
    novel_type: str = Field(min_length=1, max_length=100)
    status: str = Field(pattern=r"^(连载|完结|暂停|锁定|未知)$")
    word_count: int = Field(ge=0)
    points: int = Field(ge=0)
    published_at: datetime | None


class JjwxcBookbasePage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_page: int = Field(ge=1, le=100_000)
    total_pages: int = Field(ge=1, le=100_000)
    entries: tuple[JjwxcBookbaseEntry, ...] = Field(min_length=1, max_length=200)


class JjwxcAuthorProfileCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    author_favorite_count: int = Field(ge=0)
    nonlocked_work_count: int = Field(ge=0, le=10_000)
    locked_work_count: int = Field(ge=0, le=10_000)
    total_word_count: int = Field(ge=0)
    total_points: int = Field(ge=0)
    observed_at: datetime
    source_url: str = Field(
        pattern=r"^https://www\.jjwxc\.net/oneauthor\.php\?authorid=[1-9][0-9]{0,11}$"
    )


@dataclass(slots=True)
class _AuthorWorkRow:
    cell_depth: int = 0
    cell_parts: list[str] = field(default_factory=list)
    cells: list[str] = field(default_factory=list)
    novel_ids: list[str] = field(default_factory=list)
    locked: bool = False


class _AuthorProfileParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_AuthorWorkRow] = []
        self._row_stack: list[_AuthorWorkRow] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "tr":
            self._row_stack.append(_AuthorWorkRow())
            return
        if not self._row_stack:
            return
        if tag == "td":
            for row in self._row_stack:
                row.cell_depth += 1
        elif tag == "a":
            href = values.get("href", "")
            novel = re.search(r"onebook\.php\?novelid=([1-9][0-9]{0,11})", href)
            if novel is not None:
                for row in self._row_stack:
                    if row.cell_depth > 0 and novel.group(1) not in row.novel_ids:
                        row.novel_ids.append(novel.group(1))
            if "锁定" in values.get("rel", ""):
                for row in self._row_stack:
                    row.locked = True

    def handle_data(self, data: str) -> None:
        if not self._row_stack:
            return
        for row in self._row_stack:
            if row.cell_depth > 0:
                row.cell_parts.append(data)
            if "[锁]" in data or "本文章由作者自行锁定" in data:
                row.locked = True

    def handle_endtag(self, tag: str) -> None:
        if not self._row_stack:
            return
        if tag == "td":
            for row in self._row_stack:
                if row.cell_depth <= 0:
                    continue
                row.cell_depth -= 1
                if row.cell_depth == 0:
                    row.cells.append(" ".join("".join(row.cell_parts).split()))
                    row.cell_parts = []
        elif tag == "tr":
            row = self._row_stack.pop()
            if row.novel_ids and len(row.cells) >= 5:
                self.rows.append(row)


def parse_author_profile(
    payload: bytes,
    *,
    author_id: str,
    observed_at: datetime,
) -> JjwxcAuthorProfileCandidate:
    """Extract public author aggregates without profile prose or work titles."""
    source = decode_jjwxc_html(payload)
    favorite = re.search(r"被收藏数[：:]\s*([0-9,]+)", source)
    if favorite is None:
        raise JjwxcParseError("author_favorite_count_missing")
    parser = _AuthorProfileParser()
    parser.feed(source)
    parser.close()
    works: dict[str, tuple[bool, int, int]] = {}
    for row in parser.rows:
        novel_id = row.novel_ids[0]
        word_count = _optional_integer(row.cells[3])
        points = _optional_integer(row.cells[4])
        if word_count is None or points is None:
            continue
        current = works.get(novel_id)
        candidate = (row.locked, word_count, points)
        if current is not None and current != candidate:
            raise JjwxcParseError("author_work_row_conflict")
        works[novel_id] = candidate
    if len(works) > 10_000:
        raise JjwxcParseError("author_work_count_outside_boundary")
    nonlocked = [item for item in works.values() if not item[0]]
    return JjwxcAuthorProfileCandidate(
        author_id=author_id,
        author_favorite_count=int(favorite.group(1).replace(",", "")),
        nonlocked_work_count=len(nonlocked),
        locked_work_count=len(works) - len(nonlocked),
        total_word_count=sum(item[1] for item in nonlocked),
        total_points=sum(item[2] for item in nonlocked),
        observed_at=observed_at,
        source_url=f"https://www.jjwxc.net/oneauthor.php?authorid={author_id}",
    )


class _ChannelParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_ranking_box = False
        self.box_depth = 0
        self.ranking_list_index = -1
        self.list_depth = 0
        self.rankings: dict[str, list[JjwxcChannelRankingEntry]] = {
            key: [] for key in CHANNEL_RANKING_KEYS
        }
        self.discovered: list[str] = []
        self._anchor: dict[str, str] | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "div" and values.get("id") == "bangdan10":
            self.in_ranking_box = True
            self.box_depth = 1
            return
        if self.in_ranking_box and tag == "div":
            self.box_depth += 1
        if self.in_ranking_box and tag == "ul":
            classes = values.get("class", "").split()
            if "bdhe_lef_bod" in classes and self.ranking_list_index < 1:
                self.ranking_list_index += 1
                self.list_depth = 1
            elif self.list_depth:
                self.list_depth += 1
        if tag != "a":
            return
        href = values.get("href", "")
        match = re.search(r"onebook\.php\?novelid=([1-9][0-9]{0,11})", href)
        if match is None:
            return
        novel_id = match.group(1)
        if novel_id not in self.discovered:
            self.discovered.append(novel_id)
        if not self.in_ranking_box or self.list_depth == 0 or self.ranking_list_index > 1:
            return
        self._anchor = values
        self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None:
            self._finish_anchor()
        if self.in_ranking_box and tag == "ul" and self.list_depth:
            self.list_depth -= 1
        if self.in_ranking_box and tag == "div":
            self.box_depth -= 1
            if self.box_depth == 0:
                self.in_ranking_box = False

    def _finish_anchor(self) -> None:
        assert self._anchor is not None
        href = self._anchor.get("href", "")
        match = re.search(r"onebook\.php\?novelid=([1-9][0-9]{0,11})", href)
        if match is not None:
            ranking_key = CHANNEL_RANKING_KEYS[self.ranking_list_index]
            entries = self.rankings[ranking_key]
            title = self._anchor.get("title") or "".join(self._anchor_parts)
            title = " ".join(html_module.unescape(title).split())[:200]
            source_rank_id = None
            raw_info = self._anchor.get("data-recommendinfo")
            if raw_info:
                try:
                    info = json.loads(raw_info)
                except json.JSONDecodeError:
                    info = {}
                value = info.get("rankid")
                if isinstance(value, int | str) and str(value).isdigit():
                    source_rank_id = str(value)
            if title and not any(item.novel_id == match.group(1) for item in entries):
                entries.append(
                    JjwxcChannelRankingEntry(
                        ranking_key=ranking_key,
                        rank=len(entries) + 1,
                        novel_id=match.group(1),
                        title=title,
                        source_rank_id=source_rank_id,
                    )
                )
        self._anchor = None
        self._anchor_parts = []


def parse_channel_catalog(payload: bytes) -> JjwxcChannelCatalog:
    """Extract both named top lists and every novel identifier discoverable on the channel page."""
    source = decode_jjwxc_html(payload)
    parser = _ChannelParser()
    parser.feed(source)
    parser.close()
    rankings = {key: tuple(parser.rankings[key]) for key in CHANNEL_RANKING_KEYS}
    if any(not rankings[key] for key in CHANNEL_RANKING_KEYS):
        raise JjwxcParseError("channel_rankings_missing")
    return JjwxcChannelCatalog(
        rankings=rankings,
        discovered_novel_ids=tuple(parser.discovered),
    )


class _BookbaseParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[JjwxcBookbaseEntry] = []
        self._table_depth = 0
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._cells: list[str] = []
        self._anchor_role: str | None = None
        self._anchor_parts: list[str] = []
        self._author_id: str | None = None
        self._author_name: str | None = None
        self._novel_id: str | None = None
        self._title: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "table" and "cytable" in values.get("class", "").split():
            self._table_depth = 1
            return
        if self._table_depth == 0:
            return
        if tag == "table":
            self._table_depth += 1
        elif tag == "tr":
            self._in_row = True
            self._cells = []
            self._author_id = None
            self._author_name = None
            self._novel_id = None
            self._title = None
        elif tag == "td" and self._in_row:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "a" and self._in_cell:
            href = values.get("href", "")
            author = re.search(r"oneauthor\.php\?authorid=([1-9][0-9]{0,11})", href)
            novel = re.search(r"onebook\.php\?novelid=([1-9][0-9]{0,11})", href)
            if author is not None:
                self._anchor_role = "author"
                self._author_id = author.group(1)
                self._anchor_parts = []
            elif novel is not None:
                self._anchor_role = "novel"
                self._novel_id = novel.group(1)
                self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)
        if self._anchor_role is not None:
            self._anchor_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._table_depth == 0:
            return
        if tag == "a" and self._anchor_role is not None:
            value = " ".join("".join(self._anchor_parts).split())
            if self._anchor_role == "author":
                self._author_name = value[:80]
            else:
                self._title = value[:200]
            self._anchor_role = None
            self._anchor_parts = []
        elif tag == "td" and self._in_cell:
            self._cells.append(" ".join("".join(self._cell_parts).split()))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            self._finish_row()
            self._in_row = False
        elif tag == "table":
            self._table_depth -= 1

    def _finish_row(self) -> None:
        if (
            self._novel_id is None
            or self._author_id is None
            or not self._title
            or not self._author_name
            or len(self._cells) < 7
        ):
            return
        status_text = self._cells[3]
        status = next(
            (item for item in ("完结", "连载", "暂停", "锁定") if item in status_text),
            "未知",
        )
        published_at: datetime | None = None
        if self._cells[6]:
            try:
                published_at = datetime.strptime(
                    self._cells[6], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=_SHANGHAI)
            except ValueError:
                published_at = None
        self.entries.append(
            JjwxcBookbaseEntry(
                novel_id=self._novel_id,
                title=self._title,
                author_id=self._author_id,
                author_display_name=self._author_name,
                novel_type=self._cells[2][:100] or "未知",
                status=status,
                word_count=_optional_integer(self._cells[4]) or 0,
                points=_optional_integer(self._cells[5]) or 0,
                published_at=published_at,
            )
        )


def parse_bookbase_page(payload: bytes) -> JjwxcBookbasePage:
    """Parse one official yuri work-library page without retaining promotional copy."""
    source = decode_jjwxc_html(payload)
    parser = _BookbaseParser()
    parser.feed(source)
    parser.close()
    total = re.search(r"共\s*<font[^>]*>\s*([0-9]+)\s*</font>\s*页", source)
    current = re.search(r"当前为第\s*<font[^>]*>\s*([0-9]+)\s*</font>\s*页", source)
    if total is None or current is None or not parser.entries:
        raise JjwxcParseError("bookbase_catalog_missing")
    deduplicated = {entry.novel_id: entry for entry in parser.entries}
    return JjwxcBookbasePage(
        current_page=int(current.group(1)),
        total_pages=int(total.group(1)),
        entries=tuple(deduplicated.values()),
    )


class _ChapterDirectoryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chapters: list[JjwxcChapterMetric] = []
        self._in_row = False
        self._row_depth = 0
        self._in_cell = False
        self._cell_attrs: dict[str, str] = {}
        self._cell_parts: list[str] = []
        self._position: int | None = None
        self._chapter_id: int | None = None
        self._word_count: int | None = None
        self._click_count: int | None = None
        self._is_vip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "tr" and values.get("itemprop", "").casefold() == "chapter":
            self._in_row = True
            self._row_depth = 1
            self._position = None
            self._chapter_id = None
            self._word_count = None
            self._click_count = None
            self._is_vip = False
            return
        if not self._in_row:
            return
        if tag == "tr":
            self._row_depth += 1
        elif tag == "td":
            self._in_cell = True
            self._cell_attrs = values
            self._cell_parts = []
            click_id = values.get("clickchapterid")
            if click_id and click_id.isdigit():
                self._chapter_id = int(click_id)
        elif tag == "a":
            href = f"{values.get('href', '')} {values.get('rel', '')}"
            if match := re.search(r"chapterid=([1-9][0-9]{0,8})", href):
                self._chapter_id = int(match.group(1))
            if "onebook_vip.php" in href or values.get("id", "").startswith("vip_"):
                self._is_vip = True

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._in_row:
            return
        if tag == "td" and self._in_cell:
            text = " ".join("".join(self._cell_parts).split())
            number = _optional_integer(text)
            if self._position is None and number is not None:
                self._position = number
            if self._cell_attrs.get("itemprop", "").casefold() == "wordcount":
                self._word_count = number
            if "chapterclick" in self._cell_attrs.get("class", "").split():
                self._click_count = number
            self._in_cell = False
        elif tag == "tr":
            self._row_depth -= 1
            if self._row_depth == 0:
                self._finish_row()
                self._in_row = False

    def _finish_row(self) -> None:
        if self._chapter_id is None or self._position is None or self._word_count is None:
            return
        self.chapters.append(
            JjwxcChapterMetric(
                chapter_id=self._chapter_id,
                position=self._position,
                is_vip=self._is_vip,
                word_count=self._word_count,
                click_count=self._click_count,
            )
        )


def parse_chapter_click_payload(payload: bytes) -> dict[int, int]:
    if not payload or len(payload) > _MAX_CLICK_BYTES:
        raise JjwxcParseError("chapter_click_size_outside_boundary")
    try:
        source = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise JjwxcParseError("chapter_click_decode_failed") from exc
    match = re.fullmatch(r"\s*novelclick\((\{.*\})\)\s*;?\s*", source, re.DOTALL)
    if match is None:
        raise JjwxcParseError("chapter_click_jsonp_invalid")
    try:
        document = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise JjwxcParseError("chapter_click_json_invalid") from exc
    if not isinstance(document, dict) or len(document) > 10_000:
        raise JjwxcParseError("chapter_click_document_invalid")
    result: dict[int, int] = {}
    for raw_key, raw_value in document.items():
        if not str(raw_key).isdigit() or not str(raw_value).isdigit():
            raise JjwxcParseError("chapter_click_value_invalid")
        chapter_id = int(raw_key)
        value = int(raw_value)
        if chapter_id < 1 or value < 0:
            raise JjwxcParseError("chapter_click_value_invalid")
        result[chapter_id] = value
    return result


def parse_chapter_directory(
    page_payload: bytes,
    *,
    click_payload: bytes | None = None,
) -> tuple[JjwxcChapterMetric, ...]:
    source = decode_jjwxc_html(page_payload)
    parser = _ChapterDirectoryParser()
    parser.feed(source)
    parser.close()
    if not parser.chapters:
        return ()
    click_map = parse_chapter_click_payload(click_payload) if click_payload else {}
    parsed = tuple(
        chapter.model_copy(
            update={"click_count": click_map.get(chapter.chapter_id, chapter.click_count)}
        )
        for chapter in parser.chapters
    )
    # Some desktop pages render the same directory twice. Accept byte-equivalent chapter
    # metadata, but still fail closed when repeated identifiers disagree.
    unique: dict[int, JjwxcChapterMetric] = {}
    for chapter in parsed:
        existing = unique.get(chapter.chapter_id)
        if existing is None:
            unique[chapter.chapter_id] = chapter
        elif existing != chapter and chapter.position not in unique:
            # A few long desktop directories repeat the final published chapter URL on
            # later rows. Their visible position remains unique and is the same identifier
            # used by JJWXC's click response, so recover that identifier without prose.
            unique[chapter.position] = chapter.model_copy(
                update={
                    "chapter_id": chapter.position,
                    "click_count": click_map.get(chapter.position),
                }
            )
        elif existing != chapter:
            raise JjwxcParseError("chapter_id_conflict")
    return tuple(unique.values())


def enrich_candidate_with_chapters(
    candidate: JjwxcNovelCandidate,
    chapters: tuple[JjwxcChapterMetric, ...],
) -> JjwxcNovelCandidate:
    non_v = [item for item in chapters if not item.is_vip]
    vip = [item for item in chapters if item.is_vip]
    non_v_clicks = [item.click_count for item in non_v if item.click_count is not None]
    vip_clicks = [item.click_count for item in vip if item.click_count is not None]
    first_chapter = min(chapters, key=lambda item: item.position, default=None)
    return candidate.model_copy(
        update={
            "first_chapter_click_count": (
                first_chapter.click_count if first_chapter is not None else None
            ),
            "average_non_v_chapter_click_count": (
                sum(non_v_clicks) // len(non_v_clicks)
                if non_v_clicks
                else candidate.average_non_v_chapter_click_count
            ),
            "average_v_chapter_click_count": (
                sum(vip_clicks) // len(vip_clicks) if vip_clicks else None
            ),
            "non_v_chapter_count": len(non_v),
            "v_chapter_count": len(vip),
            "chapter_click_coverage_count": len(non_v_clicks) + len(vip_clicks),
        }
    )


def _optional_integer(value: str) -> int | None:
    cleaned = re.sub(r"[^0-9]", "", value)
    return int(cleaned) if cleaned else None
