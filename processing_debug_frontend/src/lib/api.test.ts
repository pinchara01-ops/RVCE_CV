import { describe, expect, it } from "vitest";
import { API, ApiError, apiErrorMessage } from "./api";

describe("local processing API origin", () => {
  it("uses the IPv4 loopback origin that the local launcher binds", () => {
    expect(API).toBe("http://127.0.0.1:8000");
  });

  it("shows FastAPI's safe detail instead of the raw JSON error wrapper", () => {
    expect(apiErrorMessage(new ApiError(503, '{"detail":"Qdrant timed out. Retry."}')))
      .toBe("Qdrant timed out. Retry.");
  });
});
