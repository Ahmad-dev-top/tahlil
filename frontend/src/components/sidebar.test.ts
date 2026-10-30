import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { TahlilState } from "@/hooks/useTahlil";

import { Sidebar } from "./Sidebar";

function state(publicDemo: boolean): TahlilState {
  return {
    publicDemo,
    loading: false,
    datasets: [],
    asking: false,
    conversations: [],
    conversation: null,
    dataset: null,
    schema: "",
    turns: [],
    unreachable: false,
    toast: null,
    selectDataset: async () => {},
    selectConversation: async () => {},
    newConversation: () => {},
    uploadCsv: async () => {},
    connectDatabase: async () => {},
    ask: async () => {},
    stop: () => {},
    retry: async () => {},
    dismissToast: () => {},
  } as TahlilState;
}

describe("Sidebar public demo", () => {
  it("hides the Database button when health says public_demo", () => {
    const demo = renderToStaticMarkup(createElement(Sidebar, { s: state(true) }));
    const normal = renderToStaticMarkup(createElement(Sidebar, { s: state(false) }));
    expect(demo).not.toContain("Database");
    expect(demo).not.toContain("database-button");
    expect(normal).toContain("database-button");
    expect(normal).toContain("Database");
  });
});
