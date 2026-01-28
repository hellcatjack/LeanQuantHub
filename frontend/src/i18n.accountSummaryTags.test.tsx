import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import { I18nProvider, useI18n } from "./i18n";

const TagProbe = () => {
  const { getMessage } = useI18n();
  const tags = getMessage("trade.accountSummaryTags");
  const hasNetLiquidation =
    !!tags && typeof tags === "object" && "NetLiquidation" in (tags as Record<string, unknown>);
  return <span>{hasNetLiquidation ? "yes" : "no"}</span>;
};

describe("i18n account summary tags", () => {
  it("exposes account summary tag mapping", () => {
    const html = ReactDOMServer.renderToString(
      <I18nProvider>
        <TagProbe />
      </I18nProvider>
    );
    expect(html).toContain("yes");
  });
});
