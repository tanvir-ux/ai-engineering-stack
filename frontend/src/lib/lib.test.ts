import { describe, expect, it } from "vitest";
import { applyEvent, initialState } from "./chatState";
import { challengeFor } from "./pkce";
import { buildSegmentTimeline, recordedDecision } from "./replay";
import { SseParser } from "./sse";
import type { ChatEvent, Recording } from "./types";

describe("SseParser", () => {
  it("parses events split across chunks", () => {
    const p = new SseParser();
    expect(p.push('data: {"type":"token","te')).toEqual([]);
    const out = p.push('xt":"hi"}\n\ndata: {"type":"done","status":"completed"}\n\n');
    expect(out).toEqual([
      { type: "token", text: "hi" },
      { type: "done", status: "completed" },
    ]);
  });

  it("handles CRLF and ignores comment lines", () => {
    const p = new SseParser();
    const out = p.push(': ping\r\n\r\ndata: {"type":"start","thread_id":"t1"}\r\n\r\n');
    expect(out).toEqual([{ type: "start", thread_id: "t1" }]);
  });
});

describe("applyEvent", () => {
  const events: ChatEvent[] = [
    { type: "start", thread_id: "t1" },
    {
      type: "approval_required",
      tool: "create_ticket",
      arguments: {},
      message: "Run create_ticket?",
    },
    { type: "done", status: "awaiting_approval" },
  ];

  it("tracks a pause for approval and then the decision", () => {
    let s = initialState("q");
    for (const e of events) s = applyEvent(s, e);
    expect(s.status).toBe("awaiting_approval");
    expect(s.approval?.tool).toBe("create_ticket");
    s = applyEvent(s, { type: "approval", approved: true });
    expect(s.approval).toBeNull();
    expect(s.decision).toBe("approved");
  });

  it("concatenates tokens and never mutates the previous state", () => {
    const a = initialState();
    const b = applyEvent(applyEvent(a, { type: "token", text: "Hello " }), {
      type: "token",
      text: "world",
    });
    expect(b.answer).toBe("Hello world");
    expect(a.answer).toBe("");
  });

  it("records an error", () => {
    const s = applyEvent(initialState(), { type: "error", message: "boom" });
    expect(s.status).toBe("error");
    expect(s.error).toBe("boom");
  });
});

describe("replay", () => {
  const rec = {
    segments: [
      {
        phase: "chat",
        events: [
          { type: "start", thread_id: "t", t_ms: 1 },
          { type: "token", text: "a" },
          { type: "token", text: "b" },
          { type: "done", status: "awaiting_approval", t_ms: 5000 },
        ],
      },
      { phase: "decline", events: [{ type: "done", status: "completed", t_ms: 3 }] },
    ],
  } as unknown as Recording;

  it("spaces tokens evenly and clamps long real gaps", () => {
    const tl = buildSegmentTimeline(rec.segments[0]);
    const gaps = tl.map((t, i) => t.at - (tl[i - 1]?.at ?? 0));
    expect(gaps[1]).toBe(28);
    expect(gaps[3]).toBeLessThanOrEqual(600);
    expect(tl.every((t, i) => i === 0 || t.at > tl[i - 1].at)).toBe(true);
  });

  it("reports the recorded human decision", () => {
    expect(recordedDecision(rec)).toBe("decline");
  });
});

describe("pkce", () => {
  it("matches the RFC 7636 test vector", async () => {
    const challenge = await challengeFor("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk");
    expect(challenge).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });
});
