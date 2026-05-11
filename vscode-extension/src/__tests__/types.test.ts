/**
 * Tests for types.ts — sanity checks for the harness key list and the
 * KiroOptions shape introduced for the Kiro harness.
 */

import { HARNESS_KEYS } from "../types";
import type { KiroOptions } from "../types";

describe("HARNESS_KEYS", () => {
  it("contains kiro", () => {
    expect(HARNESS_KEYS).toContain("kiro");
  });

  it("has 6 entries", () => {
    expect(HARNESS_KEYS.length).toBe(6);
  });
});

describe("KiroOptions", () => {
  it("compiles with the expected shape", () => {
    const opts: KiroOptions = { agent_name: "arize-traced", set_default: false };
    expect(opts.agent_name).toBe("arize-traced");
    expect(opts.set_default).toBe(false);
  });
});
