import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("i18n trade keys", () => {
  it("does not contain duplicate trade keys across locales", () => {
    const file = readFileSync(resolve(__dirname, "i18n.tsx"), "utf-8");
    const keys = [
      "marketHealthTitle",
      "marketHealthUpdatedAt",
      "sectionUpdatedAt",
      "receiptsTitle",
      "advancedSectionTitle",
    ];
    keys.forEach((key) => {
      const regex = new RegExp(`\\b${key}\\s*:`, "g");
      const count = (file.match(regex) || []).length;
      expect(count, key).toBe(2);
    });
  });
});
