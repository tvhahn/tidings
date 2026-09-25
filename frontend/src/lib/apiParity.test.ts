import { describe, expect, it } from "vitest";
import * as api from "@/lib/api";
import * as demoApi from "@/lib/demoApi";

// The demo build swaps `@/lib/api` for `@/lib/demoApi` via a Vite alias
// (vite.config.ts), so every runtime export of api.ts must have a demo twin —
// a missing one compiles fine in real mode and only explodes when the demo
// build resolves the import. This test turns that convention into a gate.

// Exports allowed to be missing from demoApi. Shrink this list by exporting
// the twin from demoApi, never grow it casually.
const KNOWN_ASYMMETRIES: string[] = [];

// ---------------------------------------------------------------------------
// Signature parity — enforced at compile time (`tsc -b` covers this file).
//
// Callers are type-checked against api.ts, but the demo bundle runs demoApi.
// Each demoApi export must therefore be assignable to its api.ts namesake:
// accepting every argument the real function accepts and returning something
// the real return type allows. A drifted export shows up by name in
// `SignatureDrift`, and the assignment below fails to compile.
// ---------------------------------------------------------------------------

type Api = typeof api;
type Demo = typeof demoApi;
type SharedExports = keyof Api & keyof Demo;

// Deliberate signature exceptions. Keep empty unless a mismatch is intentional
// and non-trivial; document why beside each entry.
type AllowedSignatureDrift = never;

type SignatureDrift = {
  [K in SharedExports]: Demo[K] extends Api[K] ? never : K;
}[Exclude<SharedExports, AllowedSignatureDrift>];

// Compile error here names every demoApi export whose type drifted from api.ts.
type AssertNoDrift<Drift extends never> = Drift;
const signatureParity: [AssertNoDrift<SignatureDrift>] extends [never] ? true : false = true;

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

  it("every demoApi export is type-compatible with its api.ts namesake", () => {
    // The real gate is the compile-time `signatureParity` binding above.
    expect(signatureParity).toBe(true);
  });
});
