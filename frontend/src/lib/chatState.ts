import type { ChatEvent, Chunk } from "./types";

export interface PendingApproval {
  tool: string;
  arguments: Record<string, unknown>;
  message: string;
}

export interface ChatState {
  question: string;
  threadId: string | null;
  retrieved: Chunk[];
  planNote: string | null;
  toolUsed: string | null;
  toolResult: Record<string, unknown> | null;
  denied: string | null;
  approval: PendingApproval | null;
  decision: "approved" | "declined" | null;
  answer: string;
  status: "idle" | "running" | "awaiting_approval" | "completed" | "error";
  error: string | null;
  trace: ChatEvent[];
}

export function initialState(question = ""): ChatState {
  return {
    question,
    threadId: null,
    retrieved: [],
    planNote: null,
    toolUsed: null,
    toolResult: null,
    denied: null,
    approval: null,
    decision: null,
    answer: "",
    status: "idle",
    error: null,
    trace: [],
  };
}

/** Pure reducer: fold one server-sent event into the visible chat state. */
export function applyEvent(state: ChatState, ev: ChatEvent): ChatState {
  const next: ChatState = { ...state, trace: [...state.trace, ev] };
  switch (ev.type) {
    case "start":
      next.threadId = ev.thread_id;
      next.status = "running";
      break;
    case "retrieved":
      next.retrieved = ev.chunks;
      break;
    case "plan":
      next.planNote = ev.reason;
      next.toolUsed = ev.tool;
      break;
    case "denied":
      next.denied = ev.message;
      break;
    case "approval_required":
      next.approval = { tool: ev.tool, arguments: ev.arguments, message: ev.message };
      break;
    case "approval":
      next.decision = ev.approved ? "approved" : "declined";
      next.approval = null;
      break;
    case "tool_result":
      next.toolResult = ev.result;
      break;
    case "token":
      next.answer += ev.text;
      break;
    case "done":
      next.status = ev.status;
      break;
    case "error":
      next.status = "error";
      next.error = ev.message;
      break;
    case "warning":
      break;
  }
  return next;
}
