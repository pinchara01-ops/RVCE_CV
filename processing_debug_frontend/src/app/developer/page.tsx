import Link from "next/link";

export default function DeveloperPage() {
  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">Developer options</p><h1>Configuration and evidence</h1></div>
        <Link className="secondary button" href="/">Back to search</Link>
      </div>
      <p className="muted search-intro">Search and Upload use the active API-based defaults. Change providers, keys, profiles, or inspect stored evidence here.</p>
      <section className="developer-grid">
        <Link className="developer-link" href="/architecture"><strong>Models and API setup</strong><span>Choose providers, models, Qdrant target, and session-only API keys.</span></Link>
        <Link className="developer-link" href="/library"><strong>Indexed library</strong><span>Inspect stored videos, clip windows, embeddings, transcripts, and VLM captions.</span></Link>
        <Link className="developer-link" href="/processing"><strong>Upload and processing</strong><span>Index a source video with the active runtime profile.</span></Link>
      </section>
    </main>
  );
}
