(function installPyuriPageObserver() {
  "use strict";

  const CHANNEL = "PYURI_PAGE_OBSERVER_V1";
  const MAX_RESPONSE_CHARACTERS = 5_000_000;
  const core = globalThis.PyuriCollectorCore;
  if (!core || globalThis.__PYURI_PAGE_OBSERVER_INSTALLED__) {
    return;
  }
  Object.defineProperty(globalThis, "__PYURI_PAGE_OBSERVER_INSTALLED__", {
    value: true,
    configurable: false,
    enumerable: false,
    writable: false,
  });

  const capturedRecords = new Map();

  function artworkResponseId(urlValue) {
    let parsed;
    try {
      parsed = new URL(urlValue, location.href);
    } catch {
      return null;
    }
    if (parsed.origin !== location.origin) {
      return null;
    }
    const match = parsed.pathname.match(/^\/ajax\/illust\/(\d+)\/?$/);
    return match ? match[1] : null;
  }

  function capturePayload(payload, expectedWorkId) {
    try {
      const record = core.extractFromArtworkResponse(payload, expectedWorkId);
      capturedRecords.clear();
      capturedRecords.set(expectedWorkId, record);
    } catch {
      // Fail closed. The isolated collector reports that no verified response was observed.
    }
  }

  async function captureFetchResponse(response, urlValue) {
    const expectedWorkId = artworkResponseId(urlValue);
    if (!expectedWorkId || !response || response.status !== 200) {
      return;
    }
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.toLowerCase().includes("application/json")) {
      return;
    }
    const declaredLength = Number(response.headers.get("content-length"));
    if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_CHARACTERS) {
      return;
    }
    const content = await response.clone().text();
    if (content.length === 0 || content.length > MAX_RESPONSE_CHARACTERS) {
      return;
    }
    capturePayload(JSON.parse(content), expectedWorkId);
  }

  const originalFetch = globalThis.fetch;
  if (typeof originalFetch === "function") {
    globalThis.fetch = function pyuriObservedFetch(input, init) {
      const requestUrl = typeof input === "string" || input instanceof URL ? input : input?.url;
      const result = originalFetch.call(this, input, init);
      Promise.resolve(result)
        .then((response) => captureFetchResponse(response, requestUrl))
        .catch(() => {});
      return result;
    };
  }

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function pyuriObservedOpen(method, url, ...rest) {
    this.__pyuriArtworkResponseId = String(method).toUpperCase() === "GET"
      ? artworkResponseId(url)
      : null;
    return originalOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function pyuriObservedSend(...args) {
    const expectedWorkId = this.__pyuriArtworkResponseId;
    if (expectedWorkId) {
      this.addEventListener("load", () => {
        try {
          if (this.status !== 200) {
            return;
          }
          const payload = this.responseType === "json"
            ? this.response
            : JSON.parse(this.responseText);
          capturePayload(payload, expectedWorkId);
        } catch {
          // Fail closed.
        }
      }, { once: true });
    }
    return originalSend.apply(this, args);
  };

  async function respondToCollector(message) {
    let record = capturedRecords.get(message.workId);
    let error = "page_response_not_observed";
    try {
      const currentWorkId = core.artworkIdFromUrl(location.href);
      if (currentWorkId !== message.workId) {
        throw new Error("work_id_mismatch");
      }
      if (!record && typeof originalFetch === "function") {
        const endpoint = new URL(`/ajax/illust/${currentWorkId}`, location.origin).href;
        const response = await originalFetch.call(globalThis, endpoint, {
          method: "GET",
          headers: { Accept: "application/json" },
          credentials: "same-origin",
          cache: "force-cache",
          redirect: "error",
          referrer: location.href,
          referrerPolicy: "strict-origin-when-cross-origin",
          mode: "same-origin",
        });
        await captureFetchResponse(response, endpoint);
        record = capturedRecords.get(currentWorkId);
        error = record ? null : "page_response_request_failed";
      }
    } catch {
      error = "page_response_request_failed";
    }
    globalThis.postMessage({
      channel: CHANNEL,
      type: "response",
      nonce: message.nonce,
      ok: Boolean(record),
      record: record ?? null,
      error: record ? null : error,
    }, location.origin);
  }

  globalThis.addEventListener("message", (event) => {
    const message = event.data;
    if (event.source !== globalThis || event.origin !== location.origin ||
        !message || message.channel !== CHANNEL || message.type !== "request" ||
        typeof message.nonce !== "string" || typeof message.workId !== "string") {
      return;
    }
    void respondToCollector(message);
  });
})();
