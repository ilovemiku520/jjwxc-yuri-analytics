"use strict";

const STORAGE_KEY = "pyuriJjwxcAuthorVSessionV1";
const SESSION_TTL_MS = 24 * 60 * 60 * 1000;
const MAX_RECORDS = 50000;
const attest = document.querySelector("#attest");
const collectButton = document.querySelector("#collect");
const exportButton = document.querySelector("#export");
const clearButton = document.querySelector("#clear");
const status = document.querySelector("#status");
const core = globalThis.JjwxcAuthorVCollector;

const messages = {
  author_backend_page_required: "请打开晋江作者后台的 V 章节统计页面。",
  no_exact_v_click_rows: "当前页面没有识别到带精确整数点击的 V 章节表。",
  duplicate_chapter_row: "页面包含重复章节行，已停止收集。",
  record_limit_exceeded: "当前页面超过 2000 条记录上限。",
  session_record_limit_exceeded: "本机暂存已达到 50,000 条上限，请先导出并清空。",
  invalid_collected_record: "本机暂存数据无效，建议清空后重新收集。",
};

function emptyState() {
  return { schema_version: 1, updated_at: null, expires_at: null, page_signatures: [], records: [] };
}

async function loadState() {
  const stored = (await chrome.storage.local.get(STORAGE_KEY))[STORAGE_KEY];
  if (!stored || stored.schema_version !== 1 || !Array.isArray(stored.records)) return emptyState();
  if (!stored.expires_at || Date.parse(stored.expires_at) <= Date.now()) {
    await chrome.storage.local.remove(STORAGE_KEY);
    return emptyState();
  }
  core.summarize(stored.records);
  return { ...emptyState(), ...stored, page_signatures: Array.isArray(stored.page_signatures) ? stored.page_signatures.slice(0, 1000) : [] };
}

function signatureFor(records) {
  const keys = records.map(item => `${item.novel_id}:${item.chapter_id}`).sort();
  return `${keys.length}:${keys[0] || "-"}:${keys.at(-1) || "-"}`;
}

function render(state, message) {
  const summary = core.summarize(state.records);
  const expiry = state.expires_at ? new Date(state.expires_at).toLocaleString("zh-CN", { hour12: false }) : null;
  status.textContent = message || (summary.record_count
    ? `已暂存 ${state.page_signatures.length} 页、${summary.novel_count} 部作品、${summary.record_count} 个 V 章节；${expiry} 自动过期。`
    : "尚未收集数据。请逐页点击“收集当前页”。");
  collectButton.disabled = !attest.checked;
  exportButton.disabled = !attest.checked || summary.record_count === 0;
  clearButton.disabled = summary.record_count === 0;
}

function explain(error, action = "操作") {
  const code = error instanceof Error ? error.message : "collection_failed";
  return code === "reload_extension_page_required" ? "安装或更新扩展后，请刷新作者后台页面再试。" : (messages[code] || `${action}失败（${code}）。`);
}

attest.addEventListener("change", async () => render(await loadState()));

collectButton.addEventListener("click", async () => {
  collectButton.disabled = true;
  status.textContent = "正在读取当前页的最小统计字段……";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || typeof tab.id !== "number" || !tab.url?.startsWith("https://my.jjwxc.net/")) throw new Error("author_backend_page_required");
    let response;
    try { response = await chrome.tabs.sendMessage(tab.id, { type: "PYURI_EXPORT_JJWXC_AUTHOR_V_CLICKS" }); }
    catch { throw new Error("reload_extension_page_required"); }
    if (!response?.ok || !Array.isArray(response.records)) throw new Error(response?.error || "collection_failed");
    const state = await loadState();
    const merged = core.mergeRecords(state.records, response.records, MAX_RECORDS);
    const now = new Date();
    const signature = signatureFor(response.records);
    const next = {
      schema_version: 1,
      updated_at: now.toISOString(),
      expires_at: new Date(now.getTime() + SESSION_TTL_MS).toISOString(),
      page_signatures: [...new Set([...state.page_signatures, signature])].slice(-1000),
      records: merged.records,
    };
    await chrome.storage.local.set({ [STORAGE_KEY]: next });
    render(next, `本页已收集：新增 ${merged.added_count} 条，更新 ${merged.updated_count} 条；当前共 ${core.summarize(next.records).record_count} 条。`);
  } catch (error) {
    render(await loadState(), explain(error, "收集"));
  }
});

exportButton.addEventListener("click", async () => {
  exportButton.disabled = true;
  try {
    const state = await loadState();
    const summary = core.summarize(state.records);
    if (!summary.record_count) throw new Error("no_collected_records");
    const generatedAt = new Date().toISOString();
    const payload = {
      source_format: "pyuri_jjwxc_author_v_clicks_json",
      schema_version: 1,
      generated_at: generatedAt,
      authorization_attestation: true,
      records: state.records,
    };
    const blobUrl = URL.createObjectURL(new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" }));
    try {
      await chrome.downloads.download({ url: blobUrl, filename: `pyuri-jjwxc-author-v-clicks-${summary.novel_count}-novels-${generatedAt.replaceAll(":", "-")}.json`, saveAs: false });
    } finally { setTimeout(() => URL.revokeObjectURL(blobUrl), 30000); }
    render(state, `已合并导出 ${summary.novel_count} 部作品、${summary.record_count} 个 V 章节；暂存保留，可重复导出。`);
  } catch (error) {
    render(await loadState(), explain(error, "导出"));
  }
});

clearButton.addEventListener("click", async () => {
  await chrome.storage.local.remove(STORAGE_KEY);
  render(emptyState(), "本机暂存已清空。");
});

loadState().then(state => render(state)).catch(error => { status.textContent = explain(error, "读取暂存"); });
