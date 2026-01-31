import { describe, expect, it, vi } from "vitest";

import { refreshAllWithBridgeForce } from "./liveTradeRefreshAll";

const noop = async () => {};

describe("refreshAllWithBridgeForce", () => {
  it("invokes bridge force refresh before other keys", async () => {
    const calls: string[] = [];
    const refreshHandlers = {
      connection: noop,
      account: noop,
    };
    const triggerRefresh = vi.fn(async (key: string) => {
      calls.push(`key:${key}`);
    });
    const forceBridge = vi.fn(async () => {
      calls.push("bridge");
    });

    await refreshAllWithBridgeForce({
      refreshHandlers,
      triggerRefresh,
      forceBridge,
    });

    expect(forceBridge).toHaveBeenCalledTimes(1);
    expect(calls[0]).toBe("bridge");
    expect(triggerRefresh).toHaveBeenCalledTimes(2);
  });
});
