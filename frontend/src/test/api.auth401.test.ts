import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

/**
 * The shared request() helper in services/api.ts used to intercept every
 * 401 globally -- clearing the token and hard-navigating to /login -- before
 * the response body was ever parsed. That's correct for a normal endpoint
 * (a 401 there really does mean "your session expired"), but wrong for the
 * unauthenticated auth endpoints themselves: a 401 from /api/auth/login is
 * a failed attempt, not an expired session, and the redirect raced the
 * in-flight promise on Login.tsx (see LOGIN_BUGS_FOUND.md).
 *
 * `isRedirectingTo401` is module-level state, so each test re-imports the
 * module fresh (vi.resetModules()) to avoid one test's redirect leaking
 * into the next.
 */

function mockResponse(status: number, body: unknown) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  } as Response;
}

describe("api.ts request() 401 handling", () => {
  let originalLocation: Location;

  beforeEach(() => {
    vi.resetModules();
    originalLocation = window.location;
    // jsdom's real location.href setter attempts navigation; replace it
    // with a plain writable stub so we can assert on it directly.
    // @ts-expect-error -- intentionally deleting for the test double
    delete window.location;
    window.location = { href: "" } as unknown as Location;
    localStorage.clear();
  });

  afterEach(() => {
    window.location = originalLocation;
    vi.unstubAllGlobals();
  });

  it("a 401 from /api/auth/login surfaces the server's message and does not redirect", async () => {
    localStorage.setItem("token", "stale-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockResponse(401, { error: "Invalid credentials" }))
    );

    const { authAPI } = await import("@/services/api");

    await expect(authAPI.login("someone@example.com", "wrong-password")).rejects.toThrow(
      "Invalid credentials"
    );

    expect(window.location.href).toBe("");
    // The exempted path must not have cleared an existing session token.
    expect(localStorage.getItem("token")).toBe("stale-token");
  });

  it("a 401 from a normal endpoint still clears the token and redirects", async () => {
    localStorage.setItem("token", "some-session-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockResponse(401, { error: "Token has expired" }))
    );

    const { organisationsAPI } = await import("@/services/api");

    await expect(organisationsAPI.getAll()).rejects.toThrow("Unauthorized");

    expect(localStorage.getItem("token")).toBeNull();
    expect(window.location.href).toBe("/login");
  });
});
