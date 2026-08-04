import Link from "next/link";

export default function Home() {
  return (
    <main className="home">
      <p className="eyebrow">Multimodal video retrieval</p>
      <h1>Turn a video into evidence you can inspect and search.</h1>
      <p className="lede">
        Start by indexing one video. Once its windows are stored in Qdrant,
        the same workspace lets you inspect what was saved and search it in plain language.
      </p>
      <div className="home-actions">
        <Link className="button" href="/processing">Index a video</Link>
        <Link className="button secondary" href="/library">Open indexed library</Link>
      </div>
      <ol className="workflow-list">
        <li><span>01</span><div><strong>Upload and index</strong><p>Split a video into overlapping windows and persist multimodal vectors.</p></div></li>
        <li><span>02</span><div><strong>Inspect the evidence</strong><p>Review video windows, transcripts, captions, selection rationale, and stored payloads.</p></div></li>
        <li><span>03</span><div><strong>Search the library</strong><p>Retrieve the best matching moments and play the original video at the result time.</p></div></li>
      </ol>
    </main>
  );
}
