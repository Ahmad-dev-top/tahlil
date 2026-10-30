import { API_BASE, API_KEY } from "./config";
import { SseParser } from "./sse";
import { ApiError, type AskEvent, type AskResult, type Conversation, type Dataset, type Turn } from "./types";

function headers(json = true): HeadersInit {
  return {
    ...(json ? { "Content-Type": "application/json" } : {}),
    ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
  };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...headers(!(init.body instanceof FormData)), ...init.headers } });
  } catch {
    throw new ApiError(`Cannot reach the server at ${API_BASE}`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(body?.detail ? String(body.detail) : `HTTP ${res.status}`, res.status);
  return body as T;
}

/** Absolute URL for a chart path returned by the API ("/charts/..."). */
export const chartUrl = (path: string) => `${API_BASE}${path}`;

export const api = {
  health: () => request<{ ok: boolean; public_demo?: boolean }>("/health"),

  listDatasets: () => request<Dataset[]>("/datasets"),

  datasetSchema: async (id: string) => (await request<{ schema: string }>(`/datasets/${id}`)).schema ?? "",

  uploadCsv(files: File[], name?: string) {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    if (name) form.append("name", name);
    return request<Dataset>("/datasets", { method: "POST", body: form });
  },

  connectDatabase(opts: { url: string; schema?: string; tables?: string[]; name?: string }) {
    const body = {
      url: opts.url,
      ...(opts.schema ? { schema: opts.schema } : {}),
      ...(opts.tables?.length ? { tables: opts.tables } : {}),
      ...(opts.name ? { name: opts.name } : {}),
    };
    return request<Dataset & { truncated: string[] }>("/datasets/connect", { method: "POST", body: JSON.stringify(body) });
  },

  listConversations: (datasetId: string) =>
    request<Conversation[]>(`/conversations?dataset_id=${encodeURIComponent(datasetId)}`),

  createConversation: (datasetId: string) =>
    request<Conversation>("/conversations", { method: "POST", body: JSON.stringify({ dataset_id: datasetId }) }),

  async conversationTurns(id: string): Promise<Turn[]> {
    const conv = await request<{ turns: (AskResult & { id: string })[] }>(`/conversations/${id}`);
    return conv.turns.map((t) => ({ key: t.id, question: t.question, steps: t.trace ?? [], result: t, running: false }));
  },

  /** Streams agent progress. Always ends with a "result" or an "error" event. */
  async *askStream(opts: {
    datasetId: string;
    question: string;
    conversationId?: string;
    signal?: AbortSignal;
  }): AsyncGenerator<AskEvent> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/ask/stream`, {
        method: "POST",
        headers: { ...headers(), Accept: "text/event-stream" },
        body: JSON.stringify({
          dataset_id: opts.datasetId,
          question: opts.question,
          ...(opts.conversationId ? { conversation_id: opts.conversationId } : {}),
        }),
        signal: opts.signal,
      });
    } catch {
      if (opts.signal?.aborted) return;
      yield { type: "error", message: `Cannot reach the server at ${API_BASE}` };
      return;
    }
    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => null);
      yield { type: "error", message: body?.detail ? String(body.detail) : `HTTP ${res.status}` };
      return;
    }

    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    const parser = new SseParser();
    let finished = false;
    const toEvent = (ev: { event: string; data: string }): AskEvent | null => {
      const data = JSON.parse(ev.data);
      if (ev.event === "step") return { type: "step", step: data };
      if (ev.event === "result") return { type: "result", result: data };
      if (ev.event === "error") return { type: "error", message: data.error ?? "Unknown error" };
      return null;
    };

    while (true) {
      const { value, done } = await reader.read();
      const events = done ? parser.end() : parser.push(value);
      for (const ev of events) {
        const out = toEvent(ev);
        if (!out) continue;
        if (out.type !== "step") finished = true;
        yield out;
      }
      if (done) break;
    }
    if (!finished) yield { type: "error", message: "Connection closed before the analysis finished." };
  },
};
