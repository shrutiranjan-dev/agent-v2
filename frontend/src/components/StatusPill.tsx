export function StatusPill({ value }: { value: string }) {
  return <span className={`status status-${value.replace(/[^a-z0-9_-]/gi, "").toLowerCase()}`}>{value}</span>;
}

