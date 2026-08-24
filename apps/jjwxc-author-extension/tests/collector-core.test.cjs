const assert = require("node:assert/strict");
const test = require("node:test");
const core = require("../collector-core.js");

test("normalizes exact author-owned VIP click rows", () => {
  const records = core.normalizeRows([
    { text: "13 [VIP] 12,345", position: "13", clickText: "12,345", hrefs: ["https://my.jjwxc.net/x?novelid=88&chapterid=13"] },
    { text: "14 [VIP] 100", position: "14", clickText: "100次", hrefs: ["https://my.jjwxc.net/x?novelid=88&chapterid=14"] },
  ], "https://my.jjwxc.net/x?novelid=88", "作者 VIP管理");
  assert.deepEqual(records, [
    { novel_id: "88", chapter_id: 13, click_count: 12345 },
    { novel_id: "88", chapter_id: 14, click_count: 100 },
  ]);
});

test("rejects abbreviated counts instead of inventing precision", () => {
  assert.equal(core.exactCount("1.2万"), null);
  assert.throws(() => core.normalizeRows([
    { text: "13 [VIP] 1.2万", position: "13", clickText: "1.2万", hrefs: [] },
  ], "https://my.jjwxc.net/x?novelid=88", "作者 VIP管理"), /no_exact_v_click_rows/);
});

test("merges pages, updates refreshed click counts, and sorts records", () => {
  const merged = core.mergeRecords(
    [{ novel_id: "88", chapter_id: 14, click_count: 100 }],
    [
      { novel_id: "99", chapter_id: 2, click_count: 8 },
      { novel_id: "88", chapter_id: 14, click_count: 105 },
      { novel_id: "88", chapter_id: 13, click_count: 120 },
    ],
  );
  assert.deepEqual(merged, {
    records: [
      { novel_id: "88", chapter_id: 13, click_count: 120 },
      { novel_id: "88", chapter_id: 14, click_count: 105 },
      { novel_id: "99", chapter_id: 2, click_count: 8 },
    ],
    added_count: 2,
    updated_count: 1,
  });
  assert.deepEqual(core.summarize(merged.records), { record_count: 3, novel_count: 2 });
});

test("enforces accumulated record limit and rejects invalid records", () => {
  assert.throws(() => core.mergeRecords([], [
    { novel_id: "88", chapter_id: 1, click_count: 1 },
    { novel_id: "88", chapter_id: 2, click_count: 2 },
  ], 1), /session_record_limit_exceeded/);
  assert.throws(() => core.mergeRecords([], [{ novel_id: "88", chapter_id: 0, click_count: 1 }]), /invalid_collected_record/);
});
