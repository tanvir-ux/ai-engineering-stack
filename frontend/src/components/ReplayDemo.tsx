import { useEffect, useState } from "react";
import { useReplay } from "../lib/useReplay";
import type { Recording, RecordingSummary } from "../lib/types";
import { ChatPanel } from "./ChatPanel";
import { TracePanel } from "./TracePanel";

export function ReplayDemo({ base }: { base: string }) {
  const [index, setIndex] = useState<RecordingSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [rec, setRec] = useState<Recording | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${base}recordings/index.json`)
      .then((r) => r.json() as Promise<RecordingSummary[]>)
      .then((list) => {
        setIndex(list);
        setActiveId(list[0]?.id ?? null);
      })
      .catch(() => setLoadError("Could not load the recorded sessions."));
  }, [base]);

  useEffect(() => {
    if (!activeId) return;
    fetch(`${base}recordings/${activeId}.json`)
      .then((r) => r.json() as Promise<Recording>)
      .then(setRec)
      .catch(() => setLoadError("Could not load that recording."));
  }, [base, activeId]);

  const { state, playing, decision, restart, resume } = useReplay(rec);
  const waiting = state.status === "awaiting_approval" && decision !== null;

  if (loadError) return <p className="notice deny">{loadError}</p>;

  return (
    <div className="replay">
      <div className="tabs" role="tablist">
        {index.map((s) => (
          <button
            key={s.id}
            role="tab"
            aria-selected={s.id === activeId}
            className={s.id === activeId ? "tab active" : "tab"}
            onClick={() => setActiveId(s.id)}
          >
            {s.title}
          </button>
        ))}
      </div>
      {rec && (
        <>
          <p className="blurb">{rec.blurb}</p>
          <div className="persona" data-testid="persona">
            <div>
              <strong>{rec.persona.name}</strong>
              <br />
              <small>{rec.persona.email}</small>
            </div>
            <div>
              <small>Roles</small>
              <br />
              {rec.persona.roles.join(", ")}
            </div>
            <div>
              <small>May read documents marked</small>
              <br />
              {(rec.persona.document_classes ?? []).join(", ")}
            </div>
            <div>
              <small>May use tools</small>
              <br />
              {(rec.persona.tools ?? []).join(", ") || "none"}
            </div>
          </div>
          <div className="grid">
            <section>
              <h3>Conversation</h3>
              <ChatPanel
                state={state}
                onApprove={
                  waiting
                    ? (a) => {
                        if ((a ? "approve" : "decline") === decision) resume();
                      }
                    : undefined
                }
              />
              {waiting && (
                <p className="hint">
                  This is a replay, so only the choice that was recorded can be played:{" "}
                  <strong>{decision === "approve" ? "Approve" : "Decline"}</strong>.
                </p>
              )}
              <button className="ghost" onClick={restart} disabled={playing}>
                ↻ Replay
              </button>
            </section>
            <section>
              <h3>What happened behind the scenes</h3>
              <TracePanel state={state} />
            </section>
          </div>
          <p className="fine">
            Recorded {new Date(rec.recorded_at).toLocaleString()} from the real running stack.{" "}
            {rec.note}
          </p>
        </>
      )}
    </div>
  );
}
