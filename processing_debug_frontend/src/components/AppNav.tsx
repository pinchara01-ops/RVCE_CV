import Link from "next/link";

export function AppNav() {
  return (
    <header className="app-header">
      <Link className="brand" href="/">
        <span className="brand-mark">V</span>
        <span>Video Index</span>
      </Link>
      <nav aria-label="Main navigation">
        <Link href="/">Search</Link>
        <Link href="/processing">Upload</Link>
        <Link href="/developer">Developer options</Link>
      </nav>
      <span className="header-note">API defaults active</span>
    </header>
  );
}
