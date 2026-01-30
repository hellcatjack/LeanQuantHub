import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import { I18nProvider, useI18n } from "./i18n";

const SectionProbe = () => {
  const { getMessage } = useI18n();
  const keys = [
    "trade.mainSectionTitle",
    "trade.advancedSectionTitle",
    "trade.marketHealthTitle",
    "trade.marketHealthMeta",
    "trade.marketHealthStatus",
    "trade.marketHealthUpdatedAt",
    "trade.sectionUpdatedAt",
  ];
  const results = keys.map((key) => Boolean(getMessage(key)));
  return <span>{results.every(Boolean) ? "yes" : "no"}</span>;
};

describe("i18n live trade section labels", () => {
  it("exposes new section keys", () => {
    const html = ReactDOMServer.renderToString(
      <I18nProvider>
        <SectionProbe />
      </I18nProvider>
    );
    expect(html).toContain("yes");
  });
});
