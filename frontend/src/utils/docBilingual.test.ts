import { execSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("bilingual documents", () => {
  it("requires .en.md companion for every tracked .md document", () => {
    const repoRoot = resolve(process.cwd(), "..");
    const output = execSync('git ls-files \"*.md\"', {
      cwd: repoRoot,
      encoding: "utf8",
    }).trim();
    const files = output ? output.split("\n") : [];
    const baseFiles = files.filter((file) => !file.endsWith(".en.md"));
    const missing = baseFiles.filter((file) => {
      const companion = file.replace(/\\.md$/, ".en.md");
      return !existsSync(resolve(repoRoot, companion));
    });
    expect(missing).toEqual([]);
  });

  it("requires README.en.md to be a full translation", () => {
    const repoRoot = resolve(process.cwd(), "..");
    const zh = execSync("cat README.md", { cwd: repoRoot, encoding: "utf8" });
    const en = execSync("cat README.en.md", { cwd: repoRoot, encoding: "utf8" });
    const minLength = Math.floor(zh.length * 0.7);
    expect(en.length).toBeGreaterThan(minLength);
    expect(en).not.toContain("concise translation and summary");
    expect(en).toContain("does not constitute any investment advice");
    expect(en).toContain("Local Development");
    expect(en).toContain("Server Deployment");
    expect(en).toContain("Lean Runner Configuration");
    expect(en).toContain("Data & Lifecycle Overrides");
    expect(en).toContain("TODO List Conventions");
    expect(en).toContain("Report Archive");
    expect(en).toContain("ML Scoring");
    expect(en).toContain("Security & Contributions");
  });
});
