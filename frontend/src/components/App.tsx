"use client";

import { Menu, X } from "lucide-react";
import { useEffect, useState } from "react";

import { useTahlil } from "@/hooks/useTahlil";
import { cn } from "@/lib/cn";

import { ChatView } from "./ChatView";
import { Sidebar } from "./Sidebar";

export function App() {
  const s = useTahlil();
  const [drawer, setDrawer] = useState(false);

  // auto-hide toasts
  useEffect(() => {
    if (!s.toast) return;
    const t = setTimeout(s.dismissToast, 4000);
    return () => clearTimeout(t);
  }, [s.toast, s.dismissToast]);

  return (
    <div className="flex h-dvh overflow-hidden">
      {/* desktop sidebar */}
      <div className="hidden w-72 shrink-0 border-r border-zinc-200 lg:block dark:border-zinc-800">
        <Sidebar s={s} />
      </div>

      {/* mobile drawer */}
      <div className={cn("fixed inset-0 z-40 lg:hidden", drawer ? "" : "pointer-events-none")}>
        <div
          className={cn("absolute inset-0 bg-black/40 transition-opacity", drawer ? "opacity-100" : "opacity-0")}
          onClick={() => setDrawer(false)}
        />
        <div
          className={cn(
            "absolute inset-y-0 left-0 w-80 max-w-[85vw] shadow-xl transition-transform",
            drawer ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <Sidebar s={s} onNavigate={() => setDrawer(false)} />
        </div>
      </div>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2 lg:hidden dark:border-zinc-800">
          <button onClick={() => setDrawer(true)} className="rounded-md p-2 hover:bg-zinc-100 dark:hover:bg-zinc-800" aria-label="Open menu">
            <Menu className="size-5" />
          </button>
          <span className="truncate font-medium">{s.dataset?.name ?? "Tahlil"}</span>
        </header>
        {s.loading && <div className="h-0.5 w-full animate-pulse bg-teal-600" />}
        <div className="min-h-0 flex-1">
          {s.unreachable ? (
            <div className="grid h-full place-items-center p-8 text-center" data-testid="api-unreachable">
              <div>
                <h1 className="text-xl font-semibold">API unreachable</h1>
                <p className="mt-2 text-sm text-zinc-500">The analysis server is not responding.</p>
                <button
                  type="button"
                  onClick={() => void s.retry()}
                  data-testid="retry"
                  className="mt-5 rounded-full bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800"
                >
                  Retry
                </button>
              </div>
            </div>
          ) : (
            <ChatView s={s} />
          )}
        </div>
      </main>

      {s.toast && (
        <div
          role="status"
          className={cn(
            "fixed bottom-24 left-1/2 z-50 flex max-w-[90vw] -translate-x-1/2 items-center gap-3 rounded-xl px-4 py-2.5 text-sm text-white shadow-lg",
            s.toast.kind === "error" ? "bg-red-700" : "bg-zinc-900 dark:bg-zinc-700",
          )}
        >
          <span>{s.toast.message}</span>
          <button onClick={s.dismissToast} aria-label="Dismiss" className="opacity-70 hover:opacity-100">
            <X className="size-4" />
          </button>
        </div>
      )}
    </div>
  );
}
