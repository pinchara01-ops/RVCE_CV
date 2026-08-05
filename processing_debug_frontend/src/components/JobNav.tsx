import Link from "next/link";

export function JobNav({ id }: { id: string }) {
  return <nav className="actions" aria-label="Job navigation">
    <Link className="button secondary" href={`/processing/${id}`}>Overview</Link>
    <Link className="button secondary" href={`/processing/${id}/windows`}>Windows</Link>
    <Link className="button secondary" href={`/processing/${id}/timeline`}>Timeline</Link>
  </nav>;
}
