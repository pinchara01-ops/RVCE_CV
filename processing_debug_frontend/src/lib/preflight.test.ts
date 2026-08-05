import { describe, expect, it } from "vitest";
import { summarizeCloudPreflight } from "./preflight";

describe("summarizeCloudPreflight", () => {
  it("keeps a timeout actionable instead of replacing it with a generic setup error", () => {
    const summary = summarizeCloudPreflight({
      reachable: false,
      schema_valid: false,
      timeout_seconds: 10,
      error_type: "TimeoutError",
      error: "timed out",
      diagnostics: [
        { stage: "profile_contract", status: "passed", message: "Profile selected." },
        {
          stage: "qdrant_cloud_connection",
          status: "failed",
          message: "timed out",
          elapsed_ms: 10003,
          next_action: "Check the college network and retry.",
        },
      ],
    });

    expect(summary.tone).toBe("error");
    expect(summary.headline).toBe("Qdrant Cloud connection failed");
    expect(summary.message).toContain("TimeoutError");
    expect(summary.nextAction).toBe("Check the college network and retry.");
  });

  it("explains that a missing collection is a successful first-run state", () => {
    const summary = summarizeCloudPreflight({
      reachable: true,
      collection_exists: false,
      schema_valid: true,
      diagnostics: [
        { stage: "qdrant_cloud_connection", status: "passed", message: "Connected." },
        { stage: "collection_schema", status: "warning", message: "Created on first index run." },
      ],
    });

    expect(summary.tone).toBe("warning");
    expect(summary.headline).toBe("Qdrant Cloud is ready");
    expect(summary.message).toContain("first index run");
  });
});
