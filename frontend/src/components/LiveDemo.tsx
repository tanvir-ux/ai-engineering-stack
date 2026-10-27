import { useCallback, useEffect, useState } from "react";
import { applyEvent, initialState, type ChatState } from "../lib/chatState";
import { beginLogin, completeLogin, type PkceConfig } from "../lib/pkce";
import { streamPost } from "../lib/sse";
import type { Persona } from "../lib/types";
import { ChatPanel } from "./ChatPanel";
import { TracePanel } from "./TracePanel";

const TOKEN_KEY = "aistack.token";

export function LiveDemo({ apiBase }: { apiBase: string }) {
  const cfg: PkceConfig = {
    apiBase,
    clientId: "aistack-web",
    redirectUri: `${window.location.origin}${window.location.pathname}`,
  };
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [token, setToken] = useState<string | null>(sessionStorage.getItem(TOKEN_KEY));
  const [me, setMe] = useState<{ email: string; roles: string[] } | null>(null);
  const [message, setMessage] = useState("How many days of paid holiday do I get?");
  const [state, setState] = useState<ChatState>(initialState());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${apiBase}/idp/personas`)
      .then((r) => r.json() as Promise<Persona[]>)
      .then(setPersonas)
      .catch(() => setError("The backend is not reachable at " + apiBase));
  }, [apiBase]);

  useEffect(() => {
    const search = window.location.search;
    if (search.includes("code=")) {
      completeLogin(cfg, search)
        .then((t) => {
          sessionStorage.setItem(TOKEN_KEY, t);
          setToken(t);
          window.history.replaceState({}, "", `${cfg.redirectUri}?live=${encodeURIComponent(apiBase)}`);
        })
        .catch((e: Error) => setError(e.message));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!token) return;
    fetch(`${apiBase}/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("Session expired"))))
      .then((m: { email: string; roles: string[] }) => setMe(m))
      .catch(() => {
        sessionStorage.removeItem(TOKEN_KEY);
        setToken(null);
      });
  }, [apiBase, token]);

  const run = useCallback(
    async (path: string, body: unknown, reset: boolean) => {
      if (!token) return;
      setBusy(true);
      setError(null);
      if (reset) setState(initialState(message));
      try {
        for await (const ev of streamPost(`${apiBase}${path}`, token, body)) {
          setState((s) => applyEvent(s, ev));
        }
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [apiBase, token, message],
  );

  if (!token) {
    return (
      <div>
        <p>
          Choose who to sign in as. You are sent to the identity provider and back (OIDC authorization
          code with PKCE).
        </p>
        {error && <p className="notice deny">{error}</p>}
        <div className="personas">
          {personas.map((p) => (
            <button key={p.id} className="tab" onClick={() => void beginLogin(cfg, p.id)}>
              {p.name}
              <small> {p.roles.join(", ")}</small>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <p>
        Signed in as <strong>{me?.email ?? "…"}</strong> ({me?.roles.join(", ")}){" "}
        <button
          className="ghost"
          onClick={() => {
            sessionStorage.removeItem(TOKEN_KEY);
            setToken(null);
            setMe(null);
          }}
        >
          Sign out
        </button>
      </p>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          void run("/chat", { message }, true);
        }}
      >
        <input value={message} onChange={(e) => setMessage(e.target.value)} aria-label="Question" />
        <button disabled={busy}>Ask</button>
      </form>
      {error && <p className="notice deny">{error}</p>}
      <div className="grid">
        <section>
          <h3>Conversation</h3>
          <ChatPanel
            state={state}
            busy={busy}
            onApprove={(approved) =>
              void run("/approve", { thread_id: state.threadId, approved }, false)
            }
          />
        </section>
        <section>
          <h3>What happened behind the scenes</h3>
          <TracePanel state={state} />
        </section>
      </div>
    </div>
  );
}
