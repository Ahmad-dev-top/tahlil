const intFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** Cell formatting: thousands separators, sensible decimals, ISO midnight timestamps -> dates. */
export function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return String(v);
    if (Number.isInteger(v)) return intFmt.format(v);
    const digits = Math.abs(v) >= 100 ? 1 : 3;
    return new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  const s = String(v);
  const midnight = /^(\d{4}-\d{2}-\d{2})T00:00:00(\.000)?Z?$/.exec(s);
  return midnight ? midnight[1] : s;
}

/** "1,234 tokens · $0.004". Hidden by the caller when both numbers are zero. */
export function formatUsage(tokens: number, costUsd: number): string {
  const tokenText = new Intl.NumberFormat("en-US").format(tokens);
  const cost = `$${costUsd.toFixed(4).replace(/0+$/, "").replace(/\.$/, "")}`;
  return `${tokenText} tokens · ${cost}`;
}

export function isNumericColumn(rows: Record<string, unknown>[], col: string): boolean {
  return rows.length > 0 && rows.every((r) => r[col] === null || r[col] === undefined || typeof r[col] === "number");
}
