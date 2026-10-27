import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const index = [{ id: "r1", title: "Ask a policy question", blurb: "b", question: "How many days?" }];
const rec = {
  id: "r1",
  title: "Ask a policy question",
  blurb: "Retrieval with citations.",
  question: "How many days?",
  persona: {
    id: "alice",
    name: "Alice Nguyen",
    email: "alice@example.com",
    roles: ["employee"],
    document_classes: ["public", "internal"],
    tools: ["search_docs"],
  },
  segments: [
    {
      phase: "chat",
      events: [
        { type: "start", thread_id: "t", t_ms: 1 },
        { type: "token", text: "24 days." },
        { type: "done", status: "completed", t_ms: 2 },
      ],
    },
  ],
  recorded_at: "2026-01-01T00:00:00+0000",
  note: "n",
};

describe("App (replay mode)", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ({
        ok: true,
        json: async () => (String(url).endsWith("index.json") ? index : rec),
      })),
    );
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("labels itself a recorded replay and plays the answer", async () => {
    render(<App />);
    expect(screen.getByRole("note").textContent).toMatch(/recorded replay/i);
    await waitFor(() => expect(screen.getByTestId("persona").textContent).toMatch(/Alice Nguyen/));
    await waitFor(() => expect(screen.getByTestId("answer").textContent).toBe("24 days."), {
      timeout: 3000,
    });
  });

  it("lists all ten layers", () => {
    render(<App />);
    expect(document.querySelectorAll(".layer").length).toBe(10);
  });
});
