"use strict";

const exportButton = document.querySelector("#export");
const statusNode = document.querySelector("#status");

const ERROR_MESSAGES = Object.freeze({
  age_rating_outside_g0: "作品评级不在当前 G0 许可范围内。",
  artwork_metadata_missing: "当前页面没有找到作品元数据，请刷新作品页后重试。",
  page_response_not_observed: "新版页面响应尚未捕获，请刷新作品页，等待加载完成后重试。",
  page_response_request_failed: "当前作品的单次只读元数据请求失败，请刷新页面后重试。",
  single_request_bridge_failed: "当前作品的受控单次接口回退失败，请确认登录仍有效后重试。",
  pixiv_artwork_page_required: "请先打开 pixiv.net 的单个作品页面。",
  preload_metadata_invalid: "页面元数据格式无法识别，已停止导出。",
  preload_metadata_missing_or_too_large: "页面没有提供可验证的最小元数据。",
  work_id_mismatch: "页面与作品元数据标识不一致，已停止导出。",
});

function safeMessage(code) {
  return ERROR_MESSAGES[code] ??
    `导出被安全阻止（${code}），请确认当前页面是已完整加载的 Pixiv 作品页。`;
}

function artworkIdFromTabUrl(urlValue) {
  try {
    const parsed = new URL(urlValue);
    if (parsed.protocol !== "https:" || parsed.hostname !== "www.pixiv.net") {
      return null;
    }
    return parsed.pathname.match(/^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?artworks\/(\d+)\/?$/i)?.[1] ?? null;
  } catch {
    return null;
  }
}

async function requestThroughPage(tabId, expectedWorkId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    files: ["collector-core.js"],
  });
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    args: [expectedWorkId],
    func: async (workId) => {
      try {
        const currentWorkId = globalThis.PyuriCollectorCore.artworkIdFromUrl(location.href);
        if (currentWorkId !== workId) {
          throw new Error("work_id_mismatch");
        }
        const endpoint = new URL(`/ajax/illust/${workId}`, location.origin).href;
        const response = await fetch(endpoint, {
          method: "GET",
          headers: { Accept: "application/json" },
          credentials: "same-origin",
          cache: "force-cache",
          redirect: "error",
          referrer: location.href,
          referrerPolicy: "strict-origin-when-cross-origin",
          mode: "same-origin",
        });
        if (!response.ok || response.status !== 200) {
          throw new Error("page_response_request_failed");
        }
        const declaredLength = Number(response.headers.get("content-length"));
        if (Number.isFinite(declaredLength) && declaredLength > 5_000_000) {
          throw new Error("preload_metadata_missing_or_too_large");
        }
        const content = await response.text();
        if (content.length === 0 || content.length > 5_000_000) {
          throw new Error("preload_metadata_missing_or_too_large");
        }
        const record = globalThis.PyuriCollectorCore.extractFromArtworkResponse(
          JSON.parse(content),
          workId,
        );
        return { ok: true, record };
      } catch (error) {
        const code = error instanceof Error && /^[a-z0-9_]{1,80}$/.test(error.message)
          ? error.message
          : "single_request_bridge_failed";
        return { ok: false, error: code };
      }
    },
  });
  return results?.[0]?.result ?? { ok: false, error: "single_request_bridge_failed" };
}

async function requestRecord(tab) {
  const expectedWorkId = artworkIdFromTabUrl(tab.url);
  if (!expectedWorkId || typeof tab.id !== "number") {
    return { ok: false, error: "pixiv_artwork_page_required" };
  }
  try {
    const observed = await chrome.tabs.sendMessage(
      tab.id,
      { type: "PYURI_COLLECT_CURRENT_ARTWORK" },
    );
    if (observed?.ok === true && observed.record) {
      return observed;
    }
  } catch {
    // The explicit single-request path below also supports pages opened before extension reload.
  }
  return requestThroughPage(tab.id, expectedWorkId);
}

function downloadPayload(record) {
  const generatedAt = new Date().toISOString();
  const payload = {
    source_format: "pyuri_pixiv_browser_companion_json",
    schema_version: 1,
    generated_at: generatedAt,
    records: [record],
  };
  const encoded = encodeURIComponent(`${JSON.stringify(payload, null, 2)}\n`);
  const timestamp = generatedAt.replaceAll(":", "-").replace(".000Z", "Z");
  return chrome.downloads.download({
    url: `data:application/json;charset=utf-8,${encoded}`,
    filename: `pyuri-pixiv-metadata-${record.work_id}-${timestamp}.json`,
    saveAs: false,
  });
}

exportButton.addEventListener("click", async () => {
  exportButton.disabled = true;
  statusNode.textContent = "正在检查当前作品页……";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || typeof tab.id !== "number") {
      throw new Error("active_tab_missing");
    }
    const response = await requestRecord(tab);
    if (!response || response.ok !== true || !response.record) {
      throw new Error(response?.error ?? "collection_failed");
    }
    await downloadPayload(response.record);
    statusNode.textContent = "已生成 1 条最小化元数据；请交给项目离线导入器。";
  } catch (error) {
    statusNode.textContent = safeMessage(error instanceof Error ? error.message : "collection_failed");
  } finally {
    exportButton.disabled = false;
  }
});
