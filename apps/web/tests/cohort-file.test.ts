import { describe, expect, it } from "vitest";

import {
  MAX_IMPORTED_NOVEL_IDS,
  parseCohortFile,
} from "../lib/jjwxc/cohort-file";

describe("JJWXC cohort table import", () => {
  it("reads a quoted CSV novel_id column while retaining row diagnostics", () => {
    const parsed = parseCohortFile(
      "title,novel_id\n作品甲,10806685\n作品乙,10806685\n作品丙,1.2E8\n作品丁,148682428\n",
      "cohort.csv",
    );

    expect(parsed.validIds).toEqual(["10806685", "148682428"]);
    expect(parsed.rejectedRows).toEqual([
      { rowNumber: 3, value: "10806685", reason: "duplicate_novel_id" },
      { rowNumber: 4, value: "1.2E8", reason: "invalid_novel_id" },
    ]);
  });

  it("accepts UTF-8 TSV and requires the exact novel_id header", () => {
    expect(
      parseCohortFile("\uFEFFnovel_id\t备注\n10806685\t测试", "cohort.tsv")
        .validIds,
    ).toEqual(["10806685"]);
    expect(() => parseCohortFile("作品ID\n10806685", "cohort.csv")).toThrow(
      "cohort_file_header_missing",
    );
  });

  it("caps valid unique IDs and reports excess rows", () => {
    const rows = Array.from(
      { length: MAX_IMPORTED_NOVEL_IDS + 1 },
      (_, index) => String(index + 1),
    );
    const parsed = parseCohortFile(
      `novel_id\n${rows.join("\n")}`,
      "cohort.txt",
    );

    expect(parsed.validIds).toHaveLength(MAX_IMPORTED_NOVEL_IDS);
    expect(parsed.rejectedRows.at(-1)?.reason).toBe("limit_exceeded");
  });
});
