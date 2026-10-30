import { describe, expect, it } from "vitest";

import { formatCell, formatUsage, isNumericColumn } from "../format";
import { SseParser } from "../sse";
import { stepDetail, stepLabel, stepOk } from "../steps";

describe("SseParser", () => {
  it("parses events split across arbitrary chunks", () => {
    const raw = 'event: step\ndata: {"step":"plan"}\n\nevent: result\ndata: {"status":"ok"}\n\n';
    const p = new SseParser();
    const events = [];
    for (let i = 0; i < raw.length; i += 7) events.push(...p.push(raw.slice(i, i + 7)));
    expect(events.map((e) => e.event)).toEqual(["step", "result"]);
    expect(JSON.parse(events[0].data).step).toBe("plan");
  });

  it("handles CRLF split between chunks", () => {
    const p = new SseParser();
    const out = [...p.push("event: step\r"), ...p.push("\ndata: {}\r\n\r"), ...p.push("\n")];
    expect(out).toEqual([{ event: "step", data: "{}" }]);
  });

  it("ignores comments and flushes a final event without a blank line", () => {
    const p = new SseParser();
    expect(p.push(": ping\nevent: error\ndata: {\"error\":\"x\"}")).toEqual([]);
    expect(p.end()).toEqual([{ event: "error", data: '{"error":"x"}' }]);
  });

  it("joins multi-line data", () => {
    const p = new SseParser();
    expect(p.push("data: a\ndata: b\n\n")).toEqual([{ event: "message", data: "a\nb" }]);
  });
});

describe("steps", () => {
  it("labels reflect pass/fail", () => {
    expect(stepLabel({ step: "guard_sql", passed: true })).toBe("SQL passed safety check");
    const rejected = { step: "guard_sql", passed: false, errors: ["Only SELECT"], sql: "DROP TABLE sales" };
    expect(stepOk(rejected)).toBe(false);
    expect(stepDetail(rejected)).toBe("Only SELECT\n\nDROP TABLE sales");
    expect(stepLabel({ step: "write_sql", attempt: 2 })).toBe("Wrote SQL (attempt 2)");
    expect(stepLabel({ step: "run_sql", ok: true, rows: 5 })).toBe("Ran query · 5 rows");
    expect(stepLabel({ step: "analyze", ok: true, charts: 1 })).toBe("Analysed in sandbox · 1 chart");
    expect(stepLabel({ step: "queued" })).toBe("Waiting for a free slot");
    expect(stepOk({ step: "fail" })).toBe(false);
  });
});

describe("format", () => {
  it("formats cells", () => {
    expect(formatCell(1234567)).toBe("1,234,567");
    expect(formatCell(-45151248)).toBe("-45,151,248");
    expect(formatCell(0.38196)).toBe("0.382");
    expect(formatCell(1234.56)).toBe("1,234.6");
    expect(formatCell("2025-01-01T00:00:00.000")).toBe("2025-01-01");
    expect(formatCell(null)).toBe("—");
    expect(formatUsage(1234, 0.004)).toBe("1,234 tokens · $0.004");
    expect(formatUsage(0, 0)).toBe("0 tokens · $0");
  });

  it("detects numeric columns", () => {
    expect(isNumericColumn([{ a: 1 }, { a: null }], "a")).toBe(true);
    expect(isNumericColumn([{ a: "x" }], "a")).toBe(false);
  });
});
