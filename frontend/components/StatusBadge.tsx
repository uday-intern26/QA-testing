export function statusClass(status: string | null | undefined): string {
  const name = (status || "NOT_RUN").toUpperCase();
  if (name === "PASS" || name === "SUCCESS") return "text-emerald-400 border-emerald-500/40 bg-emerald-500/10";
  if (name === "WARNING") return "text-yellow-300 border-yellow-500/40 bg-yellow-500/10";
  if (name === "FAIL" || name === "FAILED" || name === "ERROR") return "text-red-400 border-red-500/40 bg-red-500/10";
  if (name === "NOT_TESTABLE" || name === "NOT VISIBLE") return "text-zinc-300 border-zinc-600 bg-zinc-700/50";
  if (name === "RUNNING") return "text-sky-300 border-sky-500/40 bg-sky-500/10";
  return "text-zinc-400 border-zinc-700 bg-zinc-800/60";
}

export function statusMark(status: string | null | undefined): string {
  const name = (status || "NOT_RUN").toUpperCase();
  if (name === "PASS" || name === "SUCCESS") return "✓ ";
  if (name === "FAIL" || name === "FAILED" || name === "ERROR") return "✗ ";
  if (name === "WARNING") return "! ";
  if (name === "NOT_TESTABLE" || name === "NOT VISIBLE") return "– ";
  return "";
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const label = (status || "NOT RUN").replaceAll("_", " ");
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold tracking-wide ${statusClass(status)}`}>
      {statusMark(status)}
      {label}
    </span>
  );
}
