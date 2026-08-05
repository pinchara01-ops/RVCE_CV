import { describe, expect, it } from "vitest";
import { API } from "./api";

describe("local processing API origin", () => {
  it("uses the IPv4 loopback origin that the local launcher binds", () => {
    expect(API).toBe("http://127.0.0.1:8000");
  });
});
