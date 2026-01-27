export function buildOrderTag(
  tradeRunId: number,
  index: number,
  epochMs: number = Date.now(),
  rand4: number = Math.floor(Math.random() * 10000)
) {
  const padded = String(rand4).padStart(4, "0");
  return `oi_${tradeRunId}_${index}_${epochMs}_${padded}`;
}
