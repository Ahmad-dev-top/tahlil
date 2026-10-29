import type { TraceStep } from "./types";

/** false = this step reported a problem (rejected SQL, DB error, ungrounded numbers...). */
export function stepOk(s: TraceStep): boolean {
  return s.passed !== false && s.ok !== false && s.step !== "fail";
}

/** Human label for a trace entry. Add a case here whenever a node is added to app/graph.py. */
export function stepLabel(s: TraceStep): string {
  const ok = stepOk(s);
  const attempt = typeof s.attempt === "number" && s.attempt > 1 ? ` (attempt ${s.attempt})` : "";
  switch (s.step) {
    case "load_schema":
      return "Read schema";
    case "plan":
      return "Planned the analysis";
    case "write_sql":
      return `Wrote SQL${attempt}`;
    case "guard_sql":
      return ok ? "SQL passed safety check" : "SQL rejected by guard";
    case "run_sql":
      return ok ? `Ran query · ${s.rows ?? 0} rows` : "Database error";
    case "analyze": {
      if (!ok) return "Analysis code failed (continuing)";
      const n = s.charts ?? 0;
      return `Analysed in sandbox · ${n} chart${n === 1 ? "" : "s"}`;
    }
    case "report":
      return `Wrote report${attempt}`;
    case "guard_report":
      return ok ? "All numbers verified" : "Unverified numbers found";
    case "finish":
      return "Done";
    case "fail":
      return "Gave up";
    default:
      return s.step;
  }
}

export function stepDetail(s: TraceStep): string | undefined {
  if (s.step === "guard_sql" && s.passed === false) {
    const parts = [...(s.errors ?? [])];
    if (typeof s.sql === "string" && s.sql) parts.push(s.sql);
    if (parts.length) return parts.join("\n\n");
  }
  if (s.errors?.length) return s.errors.join("\n");
  if (s.error) return String(s.error);
  if (s.step === "write_sql" && typeof s.sql === "string") return s.sql;
  return undefined;
}
