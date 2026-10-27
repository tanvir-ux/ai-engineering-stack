import type { ChatState } from "../lib/chatState";

export function TracePanel({ state }: { state: ChatState }) {
  const steps = state.trace.filter((e) => e.type !== "token");
  return (
    <ol className="trace" aria-label="What the system did">
      {steps.map((e, i) => (
        <li key={i} className={`step ${e.type}`}>
          {e.type === "start" && (
            <span>
              {steps.findIndex((x) => x.type === "start") === i
                ? "Request accepted. Workflow thread started."
                : "Decision received. Workflow resumed from its saved checkpoint."}
            </span>
          )}
          {e.type === "retrieved" && (
            <span>
              Search returned {e.chunks.length} passages the user may read:
              <ul>
                {e.chunks.map((c) => (
                  <li key={c.chunk_id}>
                    {c.title} <em>({c.classification})</em>
                  </li>
                ))}
              </ul>
            </span>
          )}
          {e.type === "plan" && (
            <span>
              Agent decided: {e.action === "tool" ? `call tool “${e.tool}”` : "answer from documents"}.
              <small> {e.reason}</small>
            </span>
          )}
          {e.type === "denied" && <span>Permission check failed. {e.message}.</span>}
          {e.type === "approval_required" && <span>Workflow paused for a human decision.</span>}
          {e.type === "approval" && <span>Human {e.approved ? "approved" : "declined"} the action.</span>}
          {e.type === "tool_result" && <span>Tool “{e.tool}” ran over MCP and returned data.</span>}
          {e.type === "warning" && <span>Warning: {e.message}</span>}
          {e.type === "done" && (
            <span>{e.status === "completed" ? "Finished." : "Waiting for approval."}</span>
          )}
          {e.type === "error" && <span>Error: {e.message}</span>}
        </li>
      ))}
    </ol>
  );
}
