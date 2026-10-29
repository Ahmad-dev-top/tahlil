import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";

import { cn } from "@/lib/cn";
import { stepDetail, stepLabel, stepOk } from "@/lib/steps";
import type { TraceStep } from "@/lib/types";

/** Live agent progress: one chip per finished graph node, plus a spinner while running. */
export function StepTimeline({ steps, running }: { steps: TraceStep[]; running: boolean }) {
  const visible = steps.filter((s) => s.step !== "finish");
  return (
    <ol className="flex flex-wrap gap-1.5" aria-label="Agent steps" data-testid="steps">
      {visible.map((s, i) => {
        const ok = stepOk(s);
        return (
          <li
            key={i}
            title={stepDetail(s) ?? stepLabel(s)}
            data-testid="step"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
              ok
                ? "border-zinc-200 bg-white text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
                : "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-200",
            )}
          >
            {ok ? (
              <CheckCircle2 className="size-3.5 text-teal-600" />
            ) : (
              <AlertTriangle className="size-3.5 text-amber-600" />
            )}
            {stepLabel(s)}
          </li>
        );
      })}
      {running && (
        <li className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-zinc-300 px-2.5 py-1 text-xs text-zinc-500 dark:border-zinc-700">
          <Loader2 className="size-3.5 animate-spin" />
          {visible.length ? "Working…" : "Starting…"}
        </li>
      )}
    </ol>
  );
}
