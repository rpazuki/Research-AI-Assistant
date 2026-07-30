import { afterEach, describe, expect, it, vi } from "vitest";

describe("login route config integration", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("posts to the configured deployed backend and sets configured secure cookie", async () => {
    vi.stubEnv("RLALAB_ENV", "server");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://backend.example");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "jwt",
          token_type: "bearer",
          expires_in: 3600,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const { POST } = await import("./route");

    const response = await POST(
      new Request("http://frontend.example/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: "lab@example.com", password: "correct" }),
      })
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "https://backend.example/api/v1/auth/login",
      expect.objectContaining({ method: "POST", cache: "no-store" })
    );
    expect(response.status).toBe(200);
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("rlalab_access_token=jwt");
    expect(setCookie).toContain("Secure");
  });
});
