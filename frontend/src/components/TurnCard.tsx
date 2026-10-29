"use client";

import { Ban, ChevronRight, Code2, Copy, ListChecks, Route, ShieldAlert, ShieldCheck, Table2, XCircle } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { chartUrl } from "@/lib/api";
import { formatUsage } from "@/lib/format";
import type { AskResult, Turn } from "@/lib/types";

import { ResultTable } from "./ResultTable";
import { StepTimeline } from "./StepTimeline";

/** One question + the agent's live progress + the final answer. */
export function TurnCard({ turn }: { turn: Turn }) {
  const r = turn.result;
  return (
    <article className="min-w-0 space-y-3" data-testid="turn">
      <div className="flex justify-end">
        <p className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-teal-700 px-4 py-2.5 text-white">
          {turn.question}
        </p>
      </div>

      <StepTimeline steps={turn.steps} running={turn.running} />

      {turn.stopped && (
        <p className="text-sm font-medium text-zinc-500" data-testid="stopped">
          Stopped
        </p>
      )}
      {turn.error && <Notice icon={<XCircle className="size-5" />} text={turn.error} />}
      {r && r.status !== "ok" && r.error && <Notice icon={<Ban className="size-5" />} text={r.error} />}
      {r && r.status === "ok" && <Answer r={r} />}
    </article>
  );
}

function Answer({ r }: { r: AskResult }) {
  return (
    <div className="min-w-0 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900" data-testid="answer">
      <VerifiedBadge r={r} />
      <UsageLine r={r} />
      {r.report && (
        <div className="prose prose-sm mt-3 max-w-none overflow-x-auto break-words dark:prose-invert prose-code:before:content-none prose-code:after:content-none prose-code:rounded prose-code:bg-zinc-100 prose-code:px-1 prose-code:py-0.5 prose-code:font-normal prose-pre:overflow-x-auto dark:prose-code:bg-zinc-800 [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto">
          <Markdown remarkPlugins={[remarkGfm]}>{r.report}</Markdown>
        </div>
      )}
      {r.charts.length > 0 && (
        <div className={r.charts.length > 1 ? "mt-4 grid gap-3 sm:grid-cols-2" : ""}>
          {r.charts.map((c) => (
            // eslint-disable-next-line @next/next/no-img-element -- static export; charts are server PNGs
            <img
              key={c}
              src={chartUrl(c)}
              alt="Chart generated for this answer"
              className="mt-4 w-full max-w-full rounded-lg border border-zinc-200 bg-white p-2 dark:border-zinc-800"
            />
          ))}
        </div>
      )}
      <div className="mt-4 divide-y divide-zinc-100 border-t border-zinc-100 dark:divide-zinc-800 dark:border-zinc-800">
        {r.rows.length > 0 && (
          <Section
            icon={<Table2 className="size-4" />}
            title={`Data · ${r.row_count} row${r.row_count === 1 ? "" : "s"}${
              r.row_count > r.rows.length ? ` (first ${r.rows.length} shown)` : ""
            }`}
          >
            <ResultTable columns={r.columns} rows={r.rows} />
          </Section>
        )}
        {r.sql && (
          <Section icon={<Code2 className="size-4" />} title="SQL">
            <CodeBlock code={r.sql} />
          </Section>
        )}
        {r.plan && (
          <Section icon={<Route className="size-4" />} title="Plan">
            <p className="whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-300">{r.plan}</p>
          </Section>
        )}
        {Object.keys(r.stats ?? {}).length > 0 && (
          <Section icon={<ListChecks className="size-4" />} title="Computed stats">
            <CodeBlock code={JSON.stringify(r.stats, null, 2)} />
          </Section>
        )}
      </div>
    </div>
  );
}

function UsageLine({ r }: { r: AskResult }) {
  const tokens = r.total_tokens ?? 0;
  const cost = r.total_cost_usd ?? 0;
  if (!tokens && !cost) return null;
  return (
    <p className="mt-3 text-xs text-zinc-500" data-testid="usage">
      {formatUsage(tokens, cost)}
    </p>
  );
}

function VerifiedBadge({ r }: { r: AskResult }) {
  return r.verified ? (
    <span
      title="Every number in this report was checked against the query results."
      className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300"
      data-testid="verified"
    >
      <ShieldCheck className="size-3.5" /> Numbers verified
    </span>
  ) : (
    <span
      title={r.unverified_reason ?? "Some numbers could not be verified."}
      className="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-200"
      data-testid="unverified"
    >
      <ShieldAlert className="size-3.5" /> Not fully verified, check the data
    </span>
  );
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 py-2.5 text-left text-sm font-medium text-zinc-700 hover:text-zinc-950 dark:text-zinc-300 dark:hover:text-white"
      >
        <ChevronRight className={`size-4 transition-transform ${open ? "rotate-90" : ""}`} />
        {icon}
        {title}
      </button>
      {open && <div className="pb-3">{children}</div>}
    </div>
  );
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-lg bg-zinc-100 p-3 pr-10 font-mono text-[13px] leading-relaxed dark:bg-zinc-950">
        {code}
      </pre>
      <button
        onClick={() => {
          void navigator.clipboard?.writeText(code);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        }}
        className="absolute right-2 top-2 rounded-md p-1.5 text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-800"
        aria-label="Copy"
        title={copied ? "Copied" : "Copy"}
      >
        <Copy className="size-3.5" />
      </button>
    </div>
  );
}

function Notice({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
      <span className="shrink-0">{icon}</span>
      <p className="whitespace-pre-wrap">{text}</p>
    </div>
  );
}
