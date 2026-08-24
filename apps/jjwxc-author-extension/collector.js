"use strict";

function rowsFromDocument() {
  const rows = [];
  for (const table of document.querySelectorAll("table")) {
    const headerCells = Array.from(table.querySelectorAll("tr th, tr:first-child td")).map(cell => (cell.textContent || "").trim());
    const clickIndex = headerCells.findIndex(text => /点击|订阅/u.test(text));
    if (clickIndex < 0) continue;
    for (const row of table.querySelectorAll("tr")) {
      const cells = Array.from(row.querySelectorAll(":scope > td"));
      if (!cells.length || clickIndex >= cells.length) continue;
      rows.push({
        text: row.textContent || "",
        position: (cells[0].textContent || "").trim(),
        clickText: (cells[clickIndex].textContent || "").trim(),
        hrefs: Array.from(row.querySelectorAll("a[href]"), anchor => anchor.href),
      });
    }
  }
  return rows;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "PYURI_EXPORT_JJWXC_AUTHOR_V_CLICKS") return false;
  try {
    const records = globalThis.JjwxcAuthorVCollector.normalizeRows(rowsFromDocument(), location.href, document.body.innerText);
    sendResponse({ ok: true, records });
  } catch (error) {
    sendResponse({ ok: false, error: error instanceof Error ? error.message : "collection_failed" });
  }
  return false;
});
