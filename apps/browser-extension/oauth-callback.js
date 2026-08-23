"use strict";

const PIXIV_CALLBACK_ORIGIN = "https://app-api.pixiv.net";
const PIXIV_CALLBACK_PATH = "/web/v1/users/auth/pixiv/callback";
const LOCAL_RECEIVER = "http://127.0.0.1:41180/oauth/callback";

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    try {
      const callback = new URL(details.url);
      if (
        callback.origin !== PIXIV_CALLBACK_ORIGIN ||
        callback.pathname !== PIXIV_CALLBACK_PATH ||
        !callback.searchParams.has("code")
      ) {
        return;
      }
      void fetch(LOCAL_RECEIVER, {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: details.url,
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
      }).catch(() => undefined);
    } catch {
      // Malformed or unrelated navigation remains outside the callback bridge.
    }
  },
  { urls: ["https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback*"] },
);
