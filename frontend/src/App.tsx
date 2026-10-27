import { LayerDiagram } from "./components/LayerDiagram";
import { LiveDemo } from "./components/LiveDemo";
import { ReplayDemo } from "./components/ReplayDemo";
import { REPO } from "./lib/layers";

const LIVE_KEY = "aistack.live";

function liveBase(): string | null {
  const p = new URLSearchParams(window.location.search);
  const fromUrl = p.get("live");
  if (fromUrl) sessionStorage.setItem(LIVE_KEY, fromUrl);
  // The identity provider redirects back without our query string, so remember the backend.
  return (
    fromUrl ??
    (p.has("code") ? sessionStorage.getItem(LIVE_KEY) : null) ??
    (import.meta.env.VITE_API_BASE as string | undefined) ??
    null
  );
}

export default function App() {
  const live = liveBase();
  const base = import.meta.env.BASE_URL;
  return (
    <>
      <header className="top">
        <div>
          <h1>AI Engineering Stack</h1>
          <p className="tag">An enterprise knowledge copilot, built layer by layer.</p>
        </div>
        <a className="gh" href={REPO}>
          View on GitHub
        </a>
      </header>
      <main>
        <div className="banner" role="note">
          {live
            ? "Live mode: talking to a backend you started yourself."
            : "This page is a recorded replay of the real backend. Nothing here calls a live server or a paid AI model."}
        </div>

        <section className="intro">
          <h2>What is this?</h2>
          <p>
            Imagine a company assistant at a freight company called Meridian. You ask it a question
            in plain English. It looks through company documents, but only the ones <em>you</em> are
            allowed to read. If you ask it to do something, such as open an IT ticket, it stops and
            asks a human to approve first.
          </p>
          <p>
            It is a small, complete example of how a modern AI system is built: sign-in, permissions,
            a workflow engine, an AI agent, company tools, a data pipeline, search, monitoring and
            deployment. Every layer has real code and real tests.
          </p>
        </section>

        <section>
          <h2>Try the replay</h2>
          {live ? <LiveDemo apiBase={live} /> : <ReplayDemo base={base} />}
        </section>

        <section>
          <h2>One minute walkthrough</h2>
          <ol className="steps">
            <li>
              Open <strong>Ask a policy question</strong> and watch the answer appear with its
              source document.
            </li>
            <li>
              Compare <strong>Same question, wrong role</strong> with{" "}
              <strong>Same question, right role</strong>. The salary document exists, but only HR may
              see it.
            </li>
            <li>
              Open <strong>Take an action, with human approval</strong>. The workflow pauses until a human
              approves.
            </li>
            <li>
              Open <strong>Per-user tool permission</strong> to see a per-user rule override a role, then <strong>Role-gated analytics tool</strong> for a tool only the security role may call.
            </li>
          </ol>
        </section>

        <section>
          <h2>The ten layers</h2>
          <LayerDiagram />
        </section>

        <section className="honesty">
          <h2>What is real and what is not</h2>
          <p>
            Everything marked “Ran for real” was executed on a laptop-class machine and is covered by
            automated tests. The AI model in these recordings is a deterministic stand-in, so the
            answers show the plumbing, not the quality of a large language model. Databricks and
            Snowflake code is checked offline only. It has not been run against a live account. The
            full table is in the{" "}
            <a href={`${REPO}#what-is-verified-and-what-is-not`}>README</a>.
          </p>
        </section>
      </main>
      <footer>
        Built by <a href="https://github.com/tanvir-ux">Md Tanvir Alam</a>. MIT licensed. All data is
        synthetic.
      </footer>
    </>
  );
}
