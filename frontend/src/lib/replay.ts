import type { ChatEvent, Recording, Segment } from "./types";

export interface TimedEvent {
  at: number;
  event: ChatEvent;
}

/**
 * Turn one recorded segment into a playback timeline. Real timings are kept for non-token
 * events (retrieval, planning, tool calls) but clamped so a replay never feels slow or
 * jumpy. Tokens are spaced evenly so the streaming effect is visible.
 */
export function buildSegmentTimeline(seg: Segment, tokenGapMs = 28): TimedEvent[] {
  const out: TimedEvent[] = [];
  let clock = 0;
  let last = 0;
  for (const ev of seg.events) {
    if (ev.type === "token") {
      clock += tokenGapMs;
    } else {
      const real = (ev.t_ms ?? last) - last;
      clock += Math.min(Math.max(real, 80), 600);
      if (ev.t_ms !== undefined) last = ev.t_ms;
    }
    out.push({ at: clock, event: ev });
  }
  return out;
}

export function buildTimeline(rec: Recording): TimedEvent[][] {
  return rec.segments.map((s) => buildSegmentTimeline(s));
}

/** The recorded human decision for a recording that paused for approval, if any. */
export function recordedDecision(rec: Recording): "approve" | "decline" | null {
  const second = rec.segments[1];
  if (!second) return null;
  return second.phase === "approve" ? "approve" : second.phase === "decline" ? "decline" : null;
}
