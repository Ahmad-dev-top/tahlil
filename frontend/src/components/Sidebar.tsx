"use client";

import { Database, FileSpreadsheet, MessageSquare, Plus, Sparkles, Upload } from "lucide-react";
import { useRef, useState } from "react";

import type { TahlilState } from "@/hooks/useTahlil";
import { cn } from "@/lib/cn";

import { ConnectDialog } from "./ConnectDialog";

export function Sidebar({ s, onNavigate }: { s: TahlilState; onNavigate?: () => void }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [connectOpen, setConnectOpen] = useState(false);

  return (
    <aside className="flex h-full flex-col bg-zinc-50 dark:bg-zinc-900/60">
      <div className="px-5 pb-1 pt-5">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg bg-teal-700 text-white">
            <Sparkles className="size-4" />
          </span>
          <span className="text-lg font-semibold tracking-tight">Tahlil</span>
        </div>
        <p className="mt-1 text-xs text-zinc-500">Autonomous data analyst</p>
      </div>

      <div className="grid grid-cols-2 gap-2 px-4 pt-4">
        <button
          className="btn-tonal"
          disabled={s.loading}
          onClick={() => fileInput.current?.click()}
        >
          <Upload className="size-4" /> CSV
        </button>
        <button className="btn-tonal" disabled={s.loading} onClick={() => setConnectOpen(true)}>
          <Database className="size-4" /> Database
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".csv,text/csv"
          multiple
          hidden
          data-testid="csv-input"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) void s.uploadCsv(files).then(onNavigate);
          }}
        />
      </div>

      <h2 className="px-5 pb-1 pt-5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Datasets</h2>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {s.datasets.length === 0 && (
          <p className="px-3 py-2 text-sm text-zinc-500">Upload a CSV or connect a database to start.</p>
        )}
        {s.datasets.map((d) => {
          const active = d.id === s.dataset?.id;
          const Icon = d.source === "sql" ? Database : FileSpreadsheet;
          return (
            <div key={d.id}>
              <button
                onClick={() => {
                  void s.selectDataset(d);
                  onNavigate?.();
                }}
                className={cn(
                  "flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left",
                  active ? "bg-teal-700/10 text-teal-900 dark:text-teal-200" : "hover:bg-zinc-200/60 dark:hover:bg-zinc-800",
                )}
              >
                <Icon className="mt-0.5 size-4 shrink-0" />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{d.name}</span>
                  <span className="block truncate text-xs text-zinc-500">{d.tables.join(", ")}</span>
                </span>
              </button>

              {active && (
                <div className="mb-2 ml-5 mt-1 border-l border-zinc-200 pl-2 dark:border-zinc-800">
                  <button
                    onClick={() => {
                      s.newConversation();
                      onNavigate?.();
                    }}
                    disabled={s.asking}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-teal-800 hover:bg-zinc-200/60 disabled:opacity-50 dark:text-teal-300 dark:hover:bg-zinc-800"
                  >
                    <Plus className="size-4" /> New analysis
                  </button>
                  {s.conversations.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => {
                        void s.selectConversation(c);
                        onNavigate?.();
                      }}
                      disabled={s.asking}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm disabled:opacity-50",
                        c.id === s.conversation?.id
                          ? "bg-zinc-200/80 font-medium dark:bg-zinc-800"
                          : "text-zinc-600 hover:bg-zinc-200/60 dark:text-zinc-400 dark:hover:bg-zinc-800",
                      )}
                    >
                      <MessageSquare className="size-3.5 shrink-0" />
                      <span className="truncate">{c.title}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <ConnectDialog
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        onSubmit={async (opts) => {
          await s.connectDatabase(opts);
          setConnectOpen(false);
          onNavigate?.();
        }}
      />
    </aside>
  );
}
