import Link from "next/link";

export function AppNav() {
  return (
    <header className="app-header">
      <Link className="brand" href="/">
        <span className="brand-mark">V</span>
        <span>Video Index</span>
      </Link>
      <nav aria-label="Main navigation">
        <Link href="/architecture">Architecture</Link>
        <Link href="/processing">Index</Link>
        <Link href="/library">Library</Link>
        <Link href="/search">Search</Link>
      </nav>
      <span className="header-note">Self-hosted or API-based</span>
    </header>
  );
}
