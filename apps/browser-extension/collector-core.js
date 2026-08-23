(function installCollectorCore(root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.PyuriCollectorCore = api;
  }
})(globalThis, function createCollectorCore() {
  "use strict";

  const MAX_PRELOAD_CHARACTERS = 5_000_000;
  const MAX_TAGS = 10;
  const ALLOWED_RATINGS = new Set([0, 1, 2]);

  function fail(code) {
    throw new Error(code);
  }

  function requiredString(value, code, maxLength) {
    if (typeof value !== "string" || value.length === 0 || value.length > maxLength) {
      fail(code);
    }
    return value;
  }

  function displayString(value, code, maxLength) {
    if (typeof value !== "string" || value.length > maxLength) {
      fail(code);
    }
    return value;
  }

  function identifier(value, code) {
    const candidate = typeof value === "string"
      ? value
      : Number.isSafeInteger(value) && value > 0
        ? String(value)
        : "";
    if (!/^\d{1,64}$/.test(candidate)) {
      fail(code);
    }
    return candidate;
  }

  function positiveInteger(value, code, maximum) {
    if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
      fail(code);
    }
    return value;
  }

  function optionalCount(value, code) {
    if (value === null || typeof value === "undefined") {
      return null;
    }
    if (!Number.isSafeInteger(value) || value < 0) {
      fail(code);
    }
    return value;
  }

  function isoDate(value) {
    if (typeof value !== "string") {
      fail("created_at_invalid");
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) {
      fail("created_at_invalid");
    }
    return parsed.toISOString();
  }

  function translation(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    for (const language of ["en", "zh", "zh_tw", "ja", "ko"]) {
      const candidate = value[language];
      if (typeof candidate === "string" && candidate.length > 0 && candidate.length <= 200) {
        return candidate;
      }
    }
    return null;
  }

  function tags(value) {
    const source = value && typeof value === "object" && Array.isArray(value.tags)
      ? value.tags
      : [];
    return source.slice(0, MAX_TAGS).map((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        fail("tags_invalid");
      }
      const tagName = requiredString(item.tag, "tags_invalid", 200);
      const translated = translation(item.translation);
      return {
        tag_name: tagName,
        tag_translation: translated === tagName ? null : translated,
      };
    });
  }

  function artworkIdFromUrl(urlValue) {
    let parsed;
    try {
      parsed = new URL(urlValue);
    } catch {
      fail("page_url_invalid");
    }
    if (parsed.protocol !== "https:" || parsed.hostname !== "www.pixiv.net") {
      fail("pixiv_artwork_page_required");
    }
    const match = parsed.pathname.match(/^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?artworks\/(\d+)\/?$/i);
    if (!match) {
      fail("pixiv_artwork_page_required");
    }
    return match[1];
  }

  function extractRawArtwork(raw, expectedWorkId) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      fail("artwork_metadata_missing");
    }

    const rawId = identifier(raw.id ?? raw.illustId ?? expectedWorkId, "work_id_invalid");
    if (rawId !== expectedWorkId) {
      fail("work_id_mismatch");
    }
    if (!Number.isSafeInteger(raw.xRestrict) || !ALLOWED_RATINGS.has(raw.xRestrict)) {
      fail("age_rating_outside_g0");
    }

    return {
      work_id: rawId,
      work_title: displayString(raw.illustTitle ?? raw.title, "title_invalid", 500),
      author_id: identifier(raw.userId, "author_id_invalid"),
      author_display_name: displayString(
        raw.userName ?? raw.user,
        "author_name_invalid",
        200,
      ),
      public_tags: tags(raw.tags),
      created_at: isoDate(raw.createDate ?? raw.uploadDate),
      page_count: positiveInteger(raw.pageCount, "page_count_invalid", 10_000),
      width: positiveInteger(raw.width, "width_invalid", 100_000),
      height: positiveInteger(raw.height, "height_invalid", 100_000),
      public_view_count: optionalCount(raw.viewCount, "view_count_invalid"),
      public_bookmark_count: optionalCount(raw.bookmarkCount, "bookmark_count_invalid"),
      public_like_count: optionalCount(raw.likeCount, "like_count_invalid"),
      x_restrict: raw.xRestrict,
    };
  }

  function extractFromPreloadContent(content, expectedWorkId) {
    if (typeof content !== "string" || content.length === 0 ||
        content.length > MAX_PRELOAD_CHARACTERS) {
      fail("preload_metadata_missing_or_too_large");
    }
    let payload;
    try {
      payload = JSON.parse(content);
    } catch {
      fail("preload_metadata_invalid");
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload) ||
        !payload.illust || typeof payload.illust !== "object" || Array.isArray(payload.illust)) {
      fail("artwork_metadata_missing");
    }
    return extractRawArtwork(payload.illust[expectedWorkId], expectedWorkId);
  }

  function extractFromArtworkResponse(payload, expectedWorkId) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload) ||
        payload.error !== false || !payload.body || typeof payload.body !== "object" ||
        Array.isArray(payload.body)) {
      fail("artwork_metadata_missing");
    }
    return extractRawArtwork(payload.body, expectedWorkId);
  }

  return Object.freeze({
    artworkIdFromUrl,
    extractFromArtworkResponse,
    extractFromPreloadContent,
  });
});
