"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { ApiError, type Conversation, type Dataset, type Turn } from "@/lib/types";

export interface Toast {
  id: number;
  message: string;
  kind: "info" | "error";
}

/** All app state + actions. One hook, no state library. */
export function useTahlil() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [schema, setSchema] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [unreachable, setUnreachable] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const asking = turns.some((t) => t.running);

  const notify = useCallback((message: string, kind: Toast["kind"] = "info") => {
    setToast({ id: Date.now(), message, kind });
  }, []);

  /** Runs an action with a loading flag; errors become toasts instead of crashes. */
  const guard = useCallback(
    async (fn: () => Promise<void>) => {
      setLoading(true);
      try {
        await fn();
      } catch (e) {
        notify(e instanceof Error ? e.message : String(e), "error");
      } finally {
        setLoading(false);
      }
    },
    [notify],
  );

  const openDataset = useCallback(async (d: Dataset) => {
    abortRef.current?.abort();
    setDataset(d);
    setConversation(null);
    setTurns([]);
    setSchema("");
    const [s, convs] = await Promise.all([api.datasetSchema(d.id), api.listConversations(d.id)]);
    setSchema(s);
    setConversations(convs);
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setUnreachable(false);
    try {
      const list = await api.listDatasets();
      setDatasets(list);
      if (list.length) await openDataset(list[0]);
    } catch (e) {
      if (e instanceof ApiError && e.status === undefined) setUnreachable(true);
      else notify(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setLoading(false);
    }
  }, [notify, openDataset]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const selectDataset = useCallback((d: Dataset) => guard(() => openDataset(d)), [guard, openDataset]);

  const selectConversation = useCallback(
    (c: Conversation) =>
      guard(async () => {
        setConversation(c);
        setTurns(await api.conversationTurns(c.id));
      }),
    [guard],
  );

  const newConversation = useCallback(() => {
    setConversation(null);
    setTurns([]);
  }, []);

  const uploadCsv = useCallback(
    (files: File[]) =>
      guard(async () => {
        const d = await api.uploadCsv(files);
        setDatasets((prev) => [d, ...prev]);
        await openDataset(d);
        notify(`Loaded ${d.tables.join(", ")}`);
      }),
    [guard, openDataset, notify],
  );

  const connectDatabase = useCallback(
    (opts: { url: string; schema?: string; tables?: string[]; name?: string }) =>
      guard(async () => {
        const d = await api.connectDatabase(opts);
        setDatasets((prev) => [d, ...prev]);
        await openDataset(d);
        notify(
          d.truncated?.length
            ? `Imported. Row limit reached for: ${d.truncated.join(", ")}`
            : `Imported ${d.tables.length} table(s)`,
        );
      }),
    [guard, openDataset, notify],
  );

  const ask = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!dataset || asking || q.length < 3) return;

      const key = `t${Date.now()}`;
      const update = (fn: (t: Turn) => Turn) => setTurns((prev) => prev.map((t) => (t.key === key ? fn(t) : t)));
      const isFirst = turns.length === 0;
      setTurns((prev) => [...prev, { key, question: q, steps: [], running: true }]);

      const controller = new AbortController();
      abortRef.current = controller;
      try {
        let conv = conversation;
        if (!conv) {
          conv = await api.createConversation(dataset.id);
          setConversation(conv);
          setConversations((prev) => [conv!, ...prev]);
        }
        for await (const ev of api.askStream({
          datasetId: dataset.id,
          question: q,
          conversationId: conv.id,
          signal: controller.signal,
        })) {
          if (ev.type === "step") update((t) => ({ ...t, steps: [...t.steps, ev.step] }));
          else if (ev.type === "result") update((t) => ({ ...t, result: ev.result }));
          else update((t) => ({ ...t, error: ev.message }));
        }
        // The first question becomes the conversation title on the server.
        if (isFirst) setConversations(await api.listConversations(dataset.id));
      } catch (e) {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && e.status === undefined) setUnreachable(true);
        else update((t) => ({ ...t, error: e instanceof Error ? e.message : String(e) }));
      } finally {
        const stopped = controller.signal.aborted;
        update((t) => ({ ...t, running: false, ...(stopped ? { stopped: true } : {}) }));
      }
    },
    [dataset, asking, conversation, turns.length],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return {
    datasets, dataset, schema, conversations, conversation, turns, loading, asking, unreachable, toast,
    selectDataset, selectConversation, newConversation, uploadCsv, connectDatabase, ask, stop,
    retry: loadAll,
    dismissToast: () => setToast(null),
  };
}

export type TahlilState = ReturnType<typeof useTahlil>;
