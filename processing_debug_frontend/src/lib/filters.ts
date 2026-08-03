import type { WindowRow } from "./api";

export function filterWindows(rows: WindowRow[], filter: string, reason: string) {
  return rows.filter((row) => {
    const category =
      filter === "all" ||
      (filter === "selected" && row.selected) ||
      (filter === "skipped" && !row.selected) ||
      filter === row.provenance ||
      (filter === "failures" && row.errors.length > 0) ||
      (filter === "indexed" && row.indexed) ||
      (filter === "not_indexed" && !row.indexed);
    return category && (!reason || row.selection_reasons.includes(reason));
  });
}
