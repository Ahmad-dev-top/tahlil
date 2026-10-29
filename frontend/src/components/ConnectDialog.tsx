"use client";

import { Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (opts: { url: string; schema?: string; tables?: string[]; name?: string }) => Promise<void>;
}

export function ConnectDialog({ open, onClose, onSubmit }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget; // React clears currentTarget after the handler's first await
    const f = new FormData(form);
    const url = String(f.get("url") ?? "").trim();
    if (!url) return;
    const tables = String(f.get("tables") ?? "")
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    setBusy(true);
    try {
      await onSubmit({
        url,
        schema: String(f.get("schema") ?? "").trim() || undefined,
        tables,
        name: String(f.get("name") ?? "").trim() || undefined,
      });
      form.reset();
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl bg-white p-0 text-zinc-900 shadow-2xl backdrop:bg-black/40 dark:bg-zinc-900 dark:text-zinc-100"
    >
      <form onSubmit={submit} className="space-y-4 p-6">
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold">Connect a database</h2>
          <button type="button" onClick={onClose} className="rounded-md p-1 hover:bg-zinc-100 dark:hover:bg-zinc-800" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Tables are copied into a private snapshot. The agent never queries your database directly. Use a read-only
          user.
        </p>
        <label className="field">
          <span>Connection URL</span>
          <input name="url" required autoFocus placeholder="postgresql+psycopg://readonly:password@host:5432/shop" />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="field">
            <span>Schema (optional)</span>
            <input name="schema" placeholder="public" />
          </label>
          <label className="field">
            <span>Display name (optional)</span>
            <input name="name" placeholder="Shop DB" />
          </label>
        </div>
        <label className="field">
          <span>Tables (optional, comma-separated)</span>
          <input name="tables" placeholder="orders, customers" />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} disabled={busy} className="btn-ghost">
            Cancel
          </button>
          <button type="submit" disabled={busy} className="btn-primary">
            {busy && <Loader2 className="size-4 animate-spin" />} Import
          </button>
        </div>
      </form>
    </dialog>
  );
}
