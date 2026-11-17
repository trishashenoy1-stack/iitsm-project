/** Shimmer placeholders shown while data loads. The label is read by screen readers. */
export function Skeleton({ label, rows = 3, className = "" }: { label: string; rows?: number; className?: string }) {
  return (
    <div role="status" className={`grid gap-2.5 ${className}`}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} aria-hidden="true" className="skeleton h-14" style={{ animationDelay: `${index * 120}ms`, opacity: 1 - index * 0.2 }} />
      ))}
    </div>
  );
}
