export function CategoryBadge({ label }: { label: string }) {
  return (
    <span className="liquid-glass inline-flex whitespace-nowrap rounded-full px-3 py-1 text-xs text-paper-100">
      {label}
    </span>
  )
}
