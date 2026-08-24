export const MAX_IMPORTED_NOVEL_IDS = 100;
export const MIN_CORRELATION_SAMPLE_SIZE = 30;
export const MAX_COHORT_FILE_BYTES = 256 * 1024;

export type RejectedCohortRow = {
  rowNumber: number;
  value: string;
  reason:
    | "missing_novel_id"
    | "invalid_novel_id"
    | "duplicate_novel_id"
    | "limit_exceeded";
};

export type ParsedCohortFile = {
  validIds: string[];
  rejectedRows: RejectedCohortRow[];
  dataRowCount: number;
};

function delimiterFor(fileName: string, firstLine: string): "," | "\t" {
  const lower = fileName.toLowerCase();
  if (lower.endsWith(".tsv")) return "\t";
  if (lower.endsWith(".csv")) return ",";
  return firstLine.includes("\t") ? "\t" : ",";
}

function parseDelimited(text: string, delimiter: "," | "\t"): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
      continue;
    }
    if (!quoted && character === delimiter) {
      row.push(field);
      field = "";
      continue;
    }
    if (!quoted && (character === "\n" || character === "\r")) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      continue;
    }
    field += character;
  }
  if (quoted) throw new Error("cohort_file_unclosed_quote");
  if (field.length || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export function parseCohortFile(
  text: string,
  fileName: string,
): ParsedCohortFile {
  const normalized = text.replace(/^\uFEFF/u, "");
  const delimiter = delimiterFor(
    fileName,
    normalized.split(/\r?\n/u, 1)[0] ?? "",
  );
  const rows = parseDelimited(normalized, delimiter);
  if (!rows.length) throw new Error("cohort_file_empty");
  const headers = rows[0].map((value) => value.trim().toLowerCase());
  const novelIdIndex = headers.indexOf("novel_id");
  if (novelIdIndex < 0) throw new Error("cohort_file_header_missing");

  const validIds: string[] = [];
  const rejectedRows: RejectedCohortRow[] = [];
  const seen = new Set<string>();
  const dataRows = rows
    .slice(1)
    .filter((row) => row.some((value) => value.trim()));
  for (const [offset, row] of dataRows.entries()) {
    const rowNumber = offset + 2;
    const value = (row[novelIdIndex] ?? "").trim();
    if (!value) {
      rejectedRows.push({ rowNumber, value, reason: "missing_novel_id" });
    } else if (!/^[1-9][0-9]{0,11}$/u.test(value)) {
      rejectedRows.push({ rowNumber, value, reason: "invalid_novel_id" });
    } else if (seen.has(value)) {
      rejectedRows.push({ rowNumber, value, reason: "duplicate_novel_id" });
    } else if (validIds.length >= MAX_IMPORTED_NOVEL_IDS) {
      rejectedRows.push({ rowNumber, value, reason: "limit_exceeded" });
    } else {
      seen.add(value);
      validIds.push(value);
    }
  }
  if (!dataRows.length) throw new Error("cohort_file_no_data_rows");
  return { validIds, rejectedRows, dataRowCount: dataRows.length };
}
