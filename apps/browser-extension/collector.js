"use strict";

const SAFE_ERROR = /^[a-z0-9_]{1,80}$/;
const OBSERVER_CHANNEL = "PYURI_PAGE_OBSERVER_V1";

function requestObservedArtwork(expectedWorkId) {
  const nonce = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timeout = globalThis.setTimeout(() => {
      globalThis.removeEventListener("message", onMessage);
      reject(new Error("page_response_not_observed"));
    }, 2_000);
    function onMessage(event) {
      const response = event.data;
      if (event.source !== globalThis || event.origin !== location.origin ||
          !response || response.channel !== OBSERVER_CHANNEL || response.type !== "response" ||
          response.nonce !== nonce) {
        return;
      }
      globalThis.clearTimeout(timeout);
      globalThis.removeEventListener("message", onMessage);
      if (response.ok !== true || !response.record) {
        reject(new Error(response.error ?? "page_response_not_observed"));
        return;
      }
      resolve(response.record);
    }
    globalThis.addEventListener("message", onMessage);
    globalThis.postMessage({
      channel: OBSERVER_CHANNEL,
      type: "request",
      nonce,
      workId: expectedWorkId,
    }, location.origin);
  });
}

async function collectCurrentArtwork() {
  const expectedWorkId = globalThis.PyuriCollectorCore.artworkIdFromUrl(location.href);
  const preload = document.querySelector("meta#meta-preload-data");
  if (preload) {
    return globalThis.PyuriCollectorCore.extractFromPreloadContent(
      preload.getAttribute("content"),
      expectedWorkId,
    );
  }
  return requestObservedArtwork(expectedWorkId);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "PYURI_COLLECT_CURRENT_ARTWORK") {
    return false;
  }
  collectCurrentArtwork()
    .then((record) => sendResponse({ ok: true, record }))
    .catch((error) => {
      const candidate = error instanceof Error ? error.message : "collection_failed";
      sendResponse({
        ok: false,
        error: SAFE_ERROR.test(candidate) ? candidate : "collection_failed",
      });
    });
  return true;
});
