import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("api client errors", () => {
  it("says the server does not answer when the request never gets a response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = (await api.post("/campaigns/x/launch", {}).catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
    expect(error.message).toContain("ne répond pas");
  });

  it("keeps the server's own explanation when there is one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Target population is empty" }), {
          status: 400,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const error = (await api.post("/campaigns/x/launch", {}).catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("Target population is empty");
  });
});
