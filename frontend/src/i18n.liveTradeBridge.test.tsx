import React from "react";
import ReactDOMServer from "react-dom/server";
import { describe, expect, it } from "vitest";
import { I18nProvider, useI18n } from "./i18n";

const keys = [
  "trade.mainSectionTitle",
  "trade.marketHealthTitle",
  "trade.marketHealthUpdatedAt",
  "trade.sectionUpdatedAt",
  "trade.receiptsTitle",
  "trade.advancedSectionTitle",
];

const Probe = () => {
  const { t } = useI18n();
  const missing = keys.filter((key) => t(key) === key);
  return <span>{missing.length === 0 ? "yes" : missing.join(",")}</span>;
};

const withWindow = (locale: "zh" | "en", fn: () => string) => {
  const originalWindow = globalThis.window;
  (globalThis as typeof globalThis & { window?: Window }).window = {
    localStorage: {
      getItem: () => locale,
      setItem: () => undefined,
    },
  } as Window;
  try {
    return fn();
  } finally {
    globalThis.window = originalWindow as Window | undefined;
  }
};

describe("live trade i18n bridge keys", () => {
  it("has zh translations for live trade bridge keys", () => {
    const html = ReactDOMServer.renderToString(
      <I18nProvider>
        <Probe />
      </I18nProvider>
    );
    expect(html).toContain("yes");
  });

  it("has en translations for live trade bridge keys", () => {
    const html = withWindow("en", () =>
      ReactDOMServer.renderToString(
        <I18nProvider>
          <Probe />
        </I18nProvider>
      )
    );
    expect(html).toContain("yes");
  });
});
