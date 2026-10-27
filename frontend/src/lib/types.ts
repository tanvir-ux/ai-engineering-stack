export interface Chunk {
  chunk_id: string;
  title: string;
  classification: string;
  score: number;
}

export type ChatEvent =
  | { type: "start"; thread_id: string; t_ms?: number }
  | { type: "retrieved"; chunks: Chunk[]; t_ms?: number }
  | {
      type: "plan";
      action: "answer" | "tool";
      tool: string | null;
      reason: string;
      arguments: Record<string, unknown>;
      t_ms?: number;
    }
  | { type: "denied"; tool: string; message: string; t_ms?: number }
  | {
      type: "approval_required";
      tool: string;
      arguments: Record<string, unknown>;
      message: string;
      t_ms?: number;
    }
  | { type: "approval"; approved: boolean; t_ms?: number }
  | { type: "tool_result"; tool: string; result: Record<string, unknown>; t_ms?: number }
  | { type: "token"; text: string; t_ms?: number }
  | { type: "warning"; message: string; t_ms?: number }
  | { type: "done"; status: "completed" | "awaiting_approval"; t_ms?: number }
  | { type: "error"; message: string; t_ms?: number };

export interface Persona {
  id: string;
  email: string;
  name: string;
  roles: string[];
  document_classes?: string[];
  tools?: string[];
}

export interface Segment {
  phase: "chat" | "approve" | "decline";
  events: ChatEvent[];
}

export interface Recording {
  id: string;
  title: string;
  blurb: string;
  persona: Persona;
  question: string;
  segments: Segment[];
  recorded_at: string;
  note: string;
}

export interface RecordingSummary {
  id: string;
  title: string;
  blurb: string;
  question: string;
}
