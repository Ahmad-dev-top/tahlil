export interface Dataset {
  id: string;
  name: string;
  source: "csv" | "sql";
  source_label?: string | null;
  tables: string[];
  created_at?: number;
}

export interface Conversation {
  id: string;
  dataset_id: string;
  title: string;
  created_at?: number;
}

/** One entry of the agent trace: a LangGraph node that finished. */
export interface TraceStep {
  step: string;
  passed?: boolean;
  ok?: boolean;
  attempt?: number;
  rows?: number;
  charts?: number;
  errors?: string[];
  error?: string;
  [key: string]: unknown;
}

export type Row = Record<string, unknown>;

export interface AskResult {
  status: "ok" | "failed" | null;
  error: string | null;
  question: string;
  plan: string | null;
  sql: string | null;
  row_count: number;
  columns: string[];
  rows: Row[];
  stats: Record<string, unknown>;
  charts: string[];
  report: string | null;
  verified: boolean;
  unverified_reason: string | null;
  trace: TraceStep[];
  total_tokens?: number;
  total_cost_usd?: number;
  turn_id?: string;
}

/** A question in the chat. While running, `steps` fills in live from the stream. */
export interface Turn {
  key: string;
  question: string;
  steps: TraceStep[];
  result?: AskResult;
  error?: string;
  stopped?: boolean;
  running: boolean;
}

export type AskEvent =
  | { type: "step"; step: TraceStep }
  | { type: "result"; result: AskResult }
  | { type: "error"; message: string };

export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
  }
}
