(function install(root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.JjwxcAuthorVCollector = api;
})(globalThis, function createCollector() {
  "use strict";

  function fail(code) { throw new Error(code); }
  function idFrom(value, key) {
    const match = String(value || "").match(new RegExp(`[?&]${key}=([1-9][0-9]{0,11})`, "i"));
    return match ? match[1] : null;
  }
  function exactCount(value) {
    const cleaned = String(value || "").trim().replace(/[,，\s]/g, "").replace(/(?:次|点击)$/u, "");
    if (!/^[0-9]{1,13}$/u.test(cleaned)) return null;
    const count = Number(cleaned);
    return Number.isSafeInteger(count) ? count : null;
  }
  function normalizeRows(rawRows, pageUrl, pageText) {
    let parsed;
    try { parsed = new URL(pageUrl); } catch { fail("author_backend_page_required"); }
    if (parsed.protocol !== "https:" || parsed.hostname !== "my.jjwxc.net") fail("author_backend_page_required");
    if (!/作者|写作|作品管理|VIP管理|章节管理/u.test(pageText)) fail("author_backend_page_required");
    const pageNovelId = idFrom(pageUrl, "novelid");
    const pageIsVip = /VIP管理|VIP章节|V章统计|订阅统计/u.test(pageText);
    const output = [];
    const seen = new Set();
    for (const raw of rawRows) {
      const text = String(raw.text || "");
      if (!pageIsVip && !/\[?VIP\]?|V章/u.test(text)) continue;
      const hrefs = Array.isArray(raw.hrefs) ? raw.hrefs : [];
      const novelId = hrefs.map(href => idFrom(href, "novelid")).find(Boolean) || pageNovelId;
      const chapterId = hrefs.map(href => idFrom(href, "chapterid")).find(Boolean) || String(raw.position || "").match(/^[1-9][0-9]{0,6}$/u)?.[0];
      const clickCount = exactCount(raw.clickText);
      if (!novelId || !chapterId || clickCount === null) continue;
      const key = `${novelId}:${chapterId}`;
      if (seen.has(key)) fail("duplicate_chapter_row");
      seen.add(key);
      output.push({ novel_id: novelId, chapter_id: Number(chapterId), click_count: clickCount });
    }
    if (!output.length) fail("no_exact_v_click_rows");
    if (output.length > 2000) fail("record_limit_exceeded");
    return output;
  }
  function normalizeRecord(record) {
    const novelId = String(record?.novel_id || "");
    const chapterId = Number(record?.chapter_id);
    const clickCount = Number(record?.click_count);
    if (!/^[1-9][0-9]{0,11}$/u.test(novelId) || !Number.isSafeInteger(chapterId) || chapterId < 1 || !Number.isSafeInteger(clickCount) || clickCount < 0) fail("invalid_collected_record");
    return { novel_id: novelId, chapter_id: chapterId, click_count: clickCount };
  }
  function mergeRecords(existing, incoming, limit = 50000) {
    if (!Array.isArray(existing) || !Array.isArray(incoming)) fail("invalid_collected_record");
    const merged = new Map();
    for (const raw of existing) {
      const record = normalizeRecord(raw);
      merged.set(`${record.novel_id}:${record.chapter_id}`, record);
    }
    let addedCount = 0;
    let updatedCount = 0;
    for (const raw of incoming) {
      const record = normalizeRecord(raw);
      const key = `${record.novel_id}:${record.chapter_id}`;
      const previous = merged.get(key);
      if (!previous) addedCount += 1;
      else if (previous.click_count !== record.click_count) updatedCount += 1;
      merged.set(key, record);
    }
    if (merged.size > limit) fail("session_record_limit_exceeded");
    const records = [...merged.values()].sort((a, b) => Number(a.novel_id) - Number(b.novel_id) || a.chapter_id - b.chapter_id);
    return { records, added_count: addedCount, updated_count: updatedCount };
  }
  function summarize(records) {
    const normalized = records.map(normalizeRecord);
    return { record_count: normalized.length, novel_count: new Set(normalized.map(item => item.novel_id)).size };
  }
  return Object.freeze({ exactCount, normalizeRows, mergeRecords, summarize });
});
