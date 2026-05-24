import { describe, expect, it, vi } from "vitest";
import { apiGet } from "./api";

describe("apiGet", () => {
  it("calls fetch with the base URL prefix and returns JSON", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ hello: "world" }),
    });
    // @ts-expect-error mock
    global.fetch = mockFetch;

    const result = await apiGet<{ hello: string }>("/api/v1/test");

    expect(mockFetch).toHaveBeenCalled();
    const callUrl = mockFetch.mock.calls[0][0];
    expect(callUrl).toContain("/api/v1/test");
    expect(result).toEqual({ hello: "world" });
  });
});
