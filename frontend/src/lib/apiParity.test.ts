import { describe, expect, it } from "vitest";
import * as api from "@/lib/api";
import * as demoApi from "@/lib/demoApi";

// The demo build swaps `@/lib/api` for `@/lib/demoApi` via a Vite alias
// (vite.config.ts), so every runtime export of api.ts must have a demo twin —
// a missing one compiles fine in real mode and only explodes when the demo
// build resolves the import. This test turns that convention into a gate.

// Deliberate exception: demoApi imports txIdFromComposite from ./api for
// internal use but does not re-export it. Nothing in the demo bundle imports
// it via the aliased path (only src/test/factories.ts, which never ships).
// Shrink this list by re-exporting from demoApi, never grow it casually.
const KNOWN_ASYMMETRIES = ["txIdFromComposite"];

describe("api / demoApi export parity", () => {
  it("demoApi exports exactly the api.ts export set", () => {
    const apiExports = Object.keys(api).sort();
    const demoExports = Object.keys(demoApi).sort();

    const missingInDemo = apiExports.filter(
      (name) => !demoExports.includes(name) && !KNOWN_ASYMMETRIES.includes(name)
    );
    const extraInDemo = demoExports.filter((name) => !apiExports.includes(name));

    expect(missingInDemo, "api.ts exports with no demoApi twin").toEqual([]);
    expect(extraInDemo, "demoApi exports that api.ts does not have").toEqual([]);
  });
});
