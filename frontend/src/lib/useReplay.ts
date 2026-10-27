import { useCallback, useEffect, useRef, useState } from "react";
import { applyEvent, initialState, type ChatState } from "./chatState";
import { buildTimeline, recordedDecision } from "./replay";
import type { Recording } from "./types";

export interface ReplayControls {
  state: ChatState;
  playing: boolean;
  decision: "approve" | "decline" | null;
  restart: () => void;
  resume: () => void;
}

/** Plays a recording back as if it were arriving from the server. */
export function useReplay(rec: Recording | null): ReplayControls {
  const [state, setState] = useState<ChatState>(initialState());
  const [playing, setPlaying] = useState(false);
  const timers = useRef<number[]>([]);

  const clear = useCallback(() => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
  }, []);

  const playSegment = useCallback(
    (index: number) => {
      if (!rec) return;
      const timeline = buildTimeline(rec)[index];
      if (!timeline) return;
      setPlaying(true);
      timeline.forEach((te, i) => {
        timers.current.push(
          window.setTimeout(() => {
            setState((s) => applyEvent(s, te.event));
            if (i === timeline.length - 1) setPlaying(false);
          }, te.at),
        );
      });
    },
    [rec],
  );

  const restart = useCallback(() => {
    clear();
    setState(initialState(rec?.question ?? ""));
    playSegment(0);
  }, [clear, playSegment, rec]);

  useEffect(() => {
    restart();
    return clear;
  }, [restart, clear]);

  const resume = useCallback(() => playSegment(1), [playSegment]);

  return { state, playing, decision: rec ? recordedDecision(rec) : null, restart, resume };
}
