import type { ChatState } from "../lib/chatState";

interface Props {
  state: ChatState;
  onApprove?: (approved: boolean) => void;
  busy?: boolean;
}

export function ChatPanel({ state, onApprove, busy }: Props) {
  return (
    <div className="chat" aria-live="polite">
      {state.question && (
        <div className="bubble user" data-testid="question">
          {state.question}
        </div>
      )}
      {state.status === "running" && !state.answer && !state.approval && (
        <div className="bubble bot muted">Thinking…</div>
      )}
      {state.denied && <div className="notice deny">Blocked: {state.denied}</div>}
      {state.approval && (
        <div className="notice approve" data-testid="approval">
          <strong>Approval needed.</strong> {state.approval.message}
          {onApprove && (
            <div className="row">
              <button disabled={busy} onClick={() => onApprove(true)}>
                Approve
              </button>
              <button className="ghost" disabled={busy} onClick={() => onApprove(false)}>
                Decline
              </button>
            </div>
          )}
        </div>
      )}
      {state.toolResult && (
        <pre className="toolresult" data-testid="tool-result">
          {state.toolUsed}: {JSON.stringify(state.toolResult, null, 2)}
        </pre>
      )}
      {state.answer && (
        <div className="bubble bot" data-testid="answer">
          {state.answer}
        </div>
      )}
      {state.error && <div className="notice deny">Error: {state.error}</div>}
    </div>
  );
}
