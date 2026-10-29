"use client";

import { ArrowUp, ChevronRight, Sparkles, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { TahlilState } from "@/hooks/useTahlil";

import { TurnCard } from "./TurnCard";

const SUGGESTIONS = [
  "Which region brings in the most revenue?",
  "Show monthly revenue as a trend",
  "Which channel has the highest average order value?",
  "Top 5 products by units sold",
];

export function ChatView({ s }: { s: TahlilState }) {
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  // Scroll down when a question is added (not on every streamed step, so reading isn't interrupted).
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [s.turns.length]);

  function send(text?: string) {
    const q = (text ?? input).trim();
    if (q.length < 3 || s.asking) return;
    setInput("");
    void s.ask(q);
  }

  if (!s.dataset) {
    return (
      <div className="grid h-full place-items-center p-8 text-center">
        <div>
          <span className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-teal-700 text-white">
            <Sparkles className="size-6" />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">Ask questions about your data</h1>
          <p className="mt-2 text-zinc-500">Upload a CSV or connect a database from the sidebar.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
          {s.turns.length === 0 ? (
            <Welcome s={s} onPick={send} />
          ) : (
            <div className="space-y-10">
              {s.turns.map((t) => (
                <TurnCard key={t.key} turn={t} />
              ))}
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="border-t border-zinc-200 bg-white/80 p-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80"
      >
        <div className="mx-auto flex max-w-4xl items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={1}
            disabled={s.asking}
            placeholder={s.turns.length ? "Ask a follow-up…" : `Ask a question about ${s.dataset.name}…`}
            aria-label="Question"
            className="max-h-40 min-h-12 flex-1 resize-none rounded-3xl border border-zinc-300 bg-white px-5 py-3 outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900"
          />
          {s.asking ? (
            <button
              type="button"
              onClick={s.stop}
              aria-label="Stop"
              className="grid size-12 shrink-0 place-items-center rounded-full bg-zinc-900 text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
            >
              <Square className="size-4 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={input.trim().length < 3}
              aria-label="Send"
              className="grid size-12 shrink-0 place-items-center rounded-full bg-teal-700 text-white hover:bg-teal-800 disabled:opacity-40"
            >
              <ArrowUp className="size-5" />
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

function Welcome({ s, onPick }: { s: TahlilState; onPick: (q: string) => void }) {
  const [schemaOpen, setSchemaOpen] = useState(false);
  return (
    <div className="pt-6">
      <h1 className="text-2xl font-semibold tracking-tight">{s.dataset!.name}</h1>
      <p className="mt-1 text-sm text-zinc-500">Tables: {s.dataset!.tables.join(", ")}</p>
      <div className="mt-6 flex flex-wrap gap-2">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="rounded-full border border-zinc-300 px-3.5 py-1.5 text-sm hover:border-teal-600 hover:bg-teal-50 dark:border-zinc-700 dark:hover:bg-teal-950/40"
          >
            {q}
          </button>
        ))}
      </div>
      <button
        onClick={() => setSchemaOpen(!schemaOpen)}
        className="mt-8 flex items-center gap-1.5 text-sm font-medium text-zinc-600 dark:text-zinc-400"
        aria-expanded={schemaOpen}
      >
        <ChevronRight className={`size-4 transition-transform ${schemaOpen ? "rotate-90" : ""}`} /> Schema
      </button>
      {schemaOpen && (
        <pre className="mt-2 overflow-x-auto rounded-lg bg-zinc-100 p-3 font-mono text-xs leading-relaxed dark:bg-zinc-900">
          {s.schema || "Loading…"}
        </pre>
      )}
    </div>
  );
}
