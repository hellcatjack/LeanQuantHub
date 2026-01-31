import { getBridgeRefreshHintKey } from "./bridgeStatusExplain";

type Translator = (key: string, params?: Record<string, string>) => string;

export const formatBridgeRefreshResult = (
  t: Translator,
  value?: string | null
) => {
  if (!value) {
    return t("common.none");
  }
  const key = `trade.bridgeRefreshResult.${String(value)}`;
  const translated = t(key);
  return translated === key ? String(value) : translated;
};

export const formatBridgeRefreshReason = (
  t: Translator,
  value?: string | null
) => {
  if (!value) {
    return t("common.none");
  }
  const key = `trade.bridgeRefreshReason.${String(value)}`;
  const translated = t(key);
  return translated === key ? String(value) : translated;
};

export const getBridgeRefreshHint = (
  t: Translator,
  result?: string | null,
  reason?: string | null
) => {
  const key = getBridgeRefreshHintKey(result ?? null, reason ?? null);
  if (key === "trade.refreshHint.generic") {
    return t(key, {
      result: formatBridgeRefreshResult(t, result ?? null),
      reason: formatBridgeRefreshReason(t, reason ?? null),
    });
  }
  return t(key);
};
