export type IBStatusOverview = {
  partial?: boolean;
  connection?: { status?: string | null } | null;
} | null;

export const getOverviewStatus = (overview: IBStatusOverview): "ok" | "down" | "partial" | "unknown" => {
  if (!overview) {
    return "unknown";
  }
  if (overview.partial) {
    return "partial";
  }
  const status = overview.connection?.status || "";
  if (status === "connected") {
    return "ok";
  }
  if (status === "disconnected") {
    return "down";
  }
  return "unknown";
};
