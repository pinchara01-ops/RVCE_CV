import type { LibraryDiagnostic } from "@/lib/api";

type Props = {
  diagnostics: LibraryDiagnostic[];
};

function displayTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleTimeString();
}

/**
 * Shows only backend-redacted failures that occur after indexing, while the
 * user is navigating the persistent Qdrant-backed Library.
 */
export function LibraryDiagnostics({ diagnostics }: Props) {
  if (!diagnostics.length) return null;
  const recent = diagnostics.slice(-10).reverse();
  const latest = diagnostics[diagnostics.length - 1];

  return (
    <section className="diagnostic-section" aria-live="polite" aria-labelledby="library-diagnostics-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Library diagnostics</p>
          <h2 id="library-diagnostics-heading">What the Qdrant read attempted</h2>
          <p>These records persist across a page refresh. API keys and credential values are redacted.</p>
        </div>
        <span className="diagnostic-count">{diagnostics.length} recent event{diagnostics.length === 1 ? "" : "s"}</span>
      </div>
      <div className={`diagnostic-latest ${latest.status === "failed" ? "error" : "warning"}`}>
        <span className="diagnostic-label">Latest</span>
        <div>
          <strong>{latest.operation.replaceAll("_", " ")}</strong>
          <span>{latest.error}</span>
          <span>Collection: {latest.collection_name}</span>
          {latest.next_action && <span>{latest.next_action}</span>}
        </div>
        <time dateTime={latest.timestamp}>{displayTime(latest.timestamp)}</time>
      </div>
      <ol className="diagnostic-list">
        {recent.map((entry, index) => (
          <li className="diagnostic-row" key={`${entry.timestamp}-${entry.operation}-${entry.attempt}-${index}`}>
            <time className="diagnostic-time" dateTime={entry.timestamp}>{displayTime(entry.timestamp)}</time>
            <span className={`diagnostic-level ${entry.status === "failed" ? "error" : "warning"}`}>{entry.status}</span>
            <div className="diagnostic-message">
              <strong>{entry.operation.replaceAll("_", " ")} · attempt {entry.attempt}/{entry.attempts}</strong>
              <span>{entry.error}</span>
              <span>Collection: {entry.collection_name} · error type: {entry.error_type}</span>
              {typeof entry.elapsed_ms === "number" && <span>{entry.elapsed_ms} ms</span>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
