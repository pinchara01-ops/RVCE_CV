import type { RuntimePreflight } from "@/lib/api";
import {
  preflightDiagnostics,
  preflightStageLabel,
  summarizeCloudPreflight,
} from "@/lib/preflight";

type Props = {
  preflight?: RuntimePreflight;
  checkedAt?: string;
};

/**
 * Renders the backend's safe Cloud preflight trail. The backend redacts
 * credentials before this component ever receives a value.
 */
export function CloudPreflightDiagnostics({ preflight, checkedAt }: Props) {
  if (!preflight) return null;
  const summary = summarizeCloudPreflight(preflight);
  const diagnostics = preflightDiagnostics(preflight);

  return (
    <section className={`cloud-preflight panel ${summary.tone}`} aria-live="polite" aria-labelledby="cloud-preflight-heading">
      <div className="cloud-preflight-heading">
        <div>
          <p className="eyebrow">Connection trace</p>
          <h2 id="cloud-preflight-heading">{summary.headline}</h2>
        </div>
        {checkedAt && <time dateTime={checkedAt}>{new Date(checkedAt).toLocaleTimeString()}</time>}
      </div>
      <p className="cloud-preflight-summary">{summary.message}</p>
      {summary.nextAction && <p className="cloud-preflight-action"><strong>Next action:</strong> {summary.nextAction}</p>}
      {diagnostics.length > 0 && <ol className="cloud-preflight-list">
        {diagnostics.map((diagnostic, index) => <li className={`cloud-preflight-row ${diagnostic.status}`} key={`${diagnostic.stage}-${index}`}>
          <span className="cloud-preflight-status">{diagnostic.status}</span>
          <div>
            <strong>{preflightStageLabel(diagnostic.stage)}</strong>
            <span>{diagnostic.message}</span>
            {diagnostic.next_action && <small>{diagnostic.next_action}</small>}
          </div>
          {typeof diagnostic.elapsed_ms === "number" && <time>{diagnostic.elapsed_ms} ms</time>}
        </li>)}
      </ol>}
      <p className="cloud-preflight-note">Safe diagnostics only: provider keys and credential values are redacted.</p>
    </section>
  );
}
