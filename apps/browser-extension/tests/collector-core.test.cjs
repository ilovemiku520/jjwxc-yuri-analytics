"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const collector = require("../collector-core.js");

function preload(xRestrict = 0) {
  return JSON.stringify({
    illust: {
      "123456": {
        id: "123456",
        illustTitle: "Synthetic work",
        userId: "789",
        userName: "Synthetic author",
        tags: {
          tags: [
            { tag: "百合", translation: { en: "Yuri" } },
            { tag: "創作" },
          ],
        },
        createDate: "2026-08-23T00:00:00+09:00",
        pageCount: 1,
        width: 1200,
        height: 900,
        viewCount: 10,
        bookmarkCount: 2,
        likeCount: 3,
        xRestrict,
        urls: { original: "https://media.invalid/forbidden.jpg" },
        description: "must not be exported",
      },
    },
    user: { "789": { name: "not copied wholesale" } },
  });
}

test("extracts only approved metadata and omits media and descriptions", () => {
  const record = collector.extractFromPreloadContent(preload(), "123456");
  assert.deepEqual(Object.keys(record), [
    "work_id",
    "work_title",
    "author_id",
    "author_display_name",
    "public_tags",
    "created_at",
    "page_count",
    "width",
    "height",
    "public_view_count",
    "public_bookmark_count",
    "public_like_count",
    "x_restrict",
  ]);
  assert.equal(record.created_at, "2026-08-22T15:00:00.000Z");
  assert.equal(JSON.stringify(record).includes("media.invalid"), false);
  assert.equal(JSON.stringify(record).includes("must not be exported"), false);
});

test("accepts the three G0-approved ratings and rejects unknown ratings", () => {
  for (const rating of [0, 1, 2]) {
    assert.equal(collector.extractFromPreloadContent(preload(rating), "123456").x_restrict, rating);
  }
  assert.throws(
    () => collector.extractFromPreloadContent(preload(3), "123456"),
    /age_rating_outside_g0/,
  );
});

test("extracts the same allowlist from the current artwork response shape", () => {
  const raw = JSON.parse(preload()).illust["123456"];
  const record = collector.extractFromArtworkResponse(
    { error: false, message: "", body: { ...raw, illustId: "123456" } },
    "123456",
  );
  assert.equal(record.work_id, "123456");
  assert.equal(record.work_title, "Synthetic work");
  assert.equal(record.public_tags[0].tag_name, "百合");
  assert.equal(JSON.stringify(record).includes("media.invalid"), false);
  assert.equal(JSON.stringify(record).includes("must not be exported"), false);
});

test("rejects error responses and response ids that differ from the page", () => {
  const raw = JSON.parse(preload()).illust["123456"];
  assert.throws(
    () => collector.extractFromArtworkResponse({ error: true, body: raw }, "123456"),
    /artwork_metadata_missing/,
  );
  assert.throws(
    () => collector.extractFromArtworkResponse(
      { error: false, body: { ...raw, id: "999", illustId: "999" } },
      "123456",
    ),
    /work_id_mismatch/,
  );
});

test("requires an exact Pixiv artwork URL and matching metadata id", () => {
  assert.equal(collector.artworkIdFromUrl("https://www.pixiv.net/artworks/123456"), "123456");
  assert.equal(collector.artworkIdFromUrl("https://www.pixiv.net/en/artworks/123456"), "123456");
  assert.throws(() => collector.artworkIdFromUrl("https://example.test/artworks/123456"));
  assert.throws(() => collector.extractFromPreloadContent(preload(), "999"));
});
