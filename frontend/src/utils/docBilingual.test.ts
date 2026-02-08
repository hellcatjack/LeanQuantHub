import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const listMarkdownFiles = (repoRoot: string) => {
  const skipDirs = new Set([
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    "artifacts",
    "logs",
  ]);
  const results: string[] = [];

  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      if (skipDirs.has(entry)) {
        continue;
      }
      const full = `${dir}/${entry}`;
      const st = statSync(full);
      if (st.isDirectory()) {
        walk(full);
        continue;
      }
      if (st.isFile() && entry.endsWith(".md")) {
        results.push(full.slice(repoRoot.length + 1));
      }
    }
  };

  walk(repoRoot);
  return results;
};

describe("bilingual documents", () => {
  it("requires .en.md companion for every tracked .md document", () => {
    const repoRoot = resolve(process.cwd(), "..");
    const files = listMarkdownFiles(repoRoot);
    const baseFiles = files.filter((file) => !file.endsWith(".en.md"));
    const missing = baseFiles.filter((file) => {
      const companion = file.replace(/\\.md$/, ".en.md");
      return !existsSync(resolve(repoRoot, companion));
    });
    expect(missing).toEqual([]);
  });

  it("requires README.en.md to be a full translation", () => {
    const repoRoot = resolve(process.cwd(), "..");
    const zh = readFileSync(resolve(repoRoot, "README.md"), "utf8");
    const en = readFileSync(resolve(repoRoot, "README.en.md"), "utf8");
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
