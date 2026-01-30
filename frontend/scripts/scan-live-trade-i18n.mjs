import { chromium } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL || "http://192.168.1.31:8081";
const url = `${baseURL}/live-trade`;

const suspiciousPrefixes = [
  "trade",
  "common",
  "data",
  "projects",
  "metrics",
  "charts",
  "pretrade",
  "symbols",
  "nav",
];

const run = async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("locale", "zh");
  });
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  const matches = await page.evaluate((prefixes) => {
    const pattern = new RegExp(`\\b(?:${prefixes.join("|")})\\.[\\w.]+\\b`, "g");
    const text = document.body?.innerText || "";
    const hits = text.match(pattern) || [];
    return Array.from(new Set(hits));
  }, suspiciousPrefixes);
  await browser.close();

  if (matches.length) {
    console.log(`Found ${matches.length} suspicious i18n keys:`);
    matches.forEach((key) => console.log(`- ${key}`));
    process.exitCode = 1;
  } else {
    console.log("No suspicious i18n keys found.");
  }
};

run();
