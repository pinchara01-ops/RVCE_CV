import { describe, expect, it } from "vitest";
import { filterWindows } from "./filters";
import type { WindowRow } from "./api";

const row = (overrides: Partial<WindowRow>): WindowRow => ({
  index: 0, window_id: "v_window_0000", start: 0, end: 10, transcript: "", change_scores: {}, selected: false,
  selection_reasons: [], vlm_call_state: "skipped", caption: "", provenance: "unavailable",
  confidence: 0, indexed: false, point_id: null, vectors: {}, errors: [], ...overrides,
});

describe("filterWindows", () => {
  const rows = [
    row({ index: 0, selected: true, provenance: "direct", indexed: true, selection_reasons: ["visual_threshold"] }),
    row({ index: 1, provenance: "inherited" }),
    row({ index: 2, errors: ["failure"] }),
  ];

  it("filters selection, provenance, failure, and indexed states", () => {
    expect(filterWindows(rows, "selected", "").map((x) => x.index)).toEqual([0]);
    expect(filterWindows(rows, "inherited", "").map((x) => x.index)).toEqual([1]);
    expect(filterWindows(rows, "failures", "").map((x) => x.index)).toEqual([2]);
    expect(filterWindows(rows, "indexed", "").map((x) => x.index)).toEqual([0]);
  });

  it("filters by selection reason", () => {
    expect(filterWindows(rows, "all", "visual_threshold").map((x) => x.index)).toEqual([0]);
  });
});
