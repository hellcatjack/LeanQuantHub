import type { RefreshKey } from "./liveTradeRefreshScheduler";

type RefreshHandlers = Partial<Record<RefreshKey, () => Promise<void>>>;

type RefreshAllOptions = {
  refreshHandlers: RefreshHandlers;
  triggerRefresh: (key: RefreshKey) => Promise<void>;
  forceBridge?: () => Promise<void>;
};

export const refreshAllWithBridgeForce = async ({
  refreshHandlers,
  triggerRefresh,
  forceBridge,
}: RefreshAllOptions) => {
  if (forceBridge) {
    await forceBridge();
  }
  await Promise.all(
    (Object.keys(refreshHandlers) as RefreshKey[]).map((key) => triggerRefresh(key))
  );
};
