// Unit tests for frontend API auth plumbing + error normalization.
// Runs WITHOUT a browser or backend: `npm run test:unit` (node --test).
// NOTE: filename intentionally avoids *.spec.* / *.test.* so the Playwright
// e2e runner (testDir: ./tests) does not pick it up.
import { describe, it, afterEach } from "node:test";
import assert from "node:assert/strict";

import {
  authHeaders,
  errorMessage,
  getApiToken,
  calibrateRadar,
  enrollPlateTarget,
} from "../src/lib/api.ts";

const TOKEN_KEY = "__IBVAP_API_TOKEN__";
const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  delete globalThis[TOKEN_KEY];
});

describe("authHeaders", () => {
  it("sends X-API-Token on a mutating call (mock-fetch capture)", async () => {
    globalThis[TOKEN_KEY] = "test-token-123";
    assert.equal(getApiToken(), "test-token-123");

    let captured;
    globalThis.fetch = async (url, init) => {
      captured = { url: String(url), headers: new Headers(init?.headers) };
      return { ok: true, status: 200, json: async () => ({ status: "ok", camera_id: "c1" }) };
    };

    await calibrateRadar({ camera_id: "c1", image_points: [[0, 0]], ground_points: [[0, 0]] });

    assert.match(captured.url, /tactical\/radar\/calibrate/);
    assert.equal(captured.headers.get("X-API-Token"), "test-token-123");
    assert.equal(captured.headers.get("Content-Type"), "application/json");
  });

  it("merges extra headers without dropping the token", () => {
    globalThis[TOKEN_KEY] = "abc";
    const h = authHeaders({ "Content-Type": "application/json" });
    assert.equal(h["X-API-Token"], "abc");
    assert.equal(h["content-type"], "application/json");
  });
});

describe("errorMessage", () => {
  it("extracts message from {code, message} object details", async () => {
    globalThis[TOKEN_KEY] = "t";
    globalThis.fetch = async () => ({
      ok: false,
      status: 400,
      json: async () => ({ detail: { code: "invalid_plate", message: "Bad plate" } }),
    });
    await assert.rejects(enrollPlateTarget({ name: "n", plate_number: "X" }), /Bad plate/);
    assert.equal(errorMessage({ code: "x", message: "Boom" }, "fallback"), "Boom");
  });

  it("passes plain-string details through (evidence/models/uploads shape)", async () => {
    globalThis[TOKEN_KEY] = "t";
    globalThis.fetch = async () => ({
      ok: false,
      status: 400,
      json: async () => ({ detail: "plain failure" }),
    });
    await assert.rejects(enrollPlateTarget({ name: "n", plate_number: "X" }), /plain failure/);
    assert.equal(errorMessage("plain failure", "fallback"), "plain failure");
    assert.equal(errorMessage(undefined, "fallback"), "fallback");
  });

  it("never renders [object Object]", () => {
    assert.ok(!errorMessage({ code: "x", message: "m" }, "f").includes("[object Object]"));
    assert.ok(!errorMessage({ code: "x" }, "f").includes("[object Object]"));
  });
});
