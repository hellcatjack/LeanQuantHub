import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("document policy", () => {
  it("requires bilingual output with .en.md companions", () => {
    const policy = readFileSync(resolve(process.cwd(), "../AGENTS.md"), "utf8");
    expect(policy).toContain("双语");
    expect(policy).toContain(".en.md");
  });
});
