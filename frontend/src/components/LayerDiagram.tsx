import { LAYERS, REPO, STATUS_TEXT } from "../lib/layers";

export function LayerDiagram() {
  return (
    <ol className="layers">
      {LAYERS.map((l, i) => (
        <li key={l.id} className={`layer ${l.status}`}>
          <span className="num">{i + 1}</span>
          <div className="body">
            <h3>
              {l.name} <small>{l.tech}</small>
            </h3>
            <p>{l.what}</p>
            <p className="meta">
              <span className={`chip ${l.status}`} title={STATUS_TEXT[l.status]}>
                {l.statusLabel}
              </span>{" "}
              <a href={`${REPO}/tree/master/${l.path}`}>View the code →</a>
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
