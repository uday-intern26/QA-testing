const toneFor = (value: string) => {
  const key = value.toLowerCase();
  if (["healthy", "passed", "completed", "ok", "approved", "none"].includes(key)) {
    return "bg-emerald-950 text-emerald-300 border-emerald-800";
  }
  if (["failed", "error", "degraded", "application_defect"].includes(key)) {
    return "bg-red-950 text-red-300 border-red-800";
  }
  if (["needs_review", "blocked", "inconclusive", "ambiguous_requirement", "queued", "running"].includes(key)) {
    return "bg-amber-950 text-amber-300 border-amber-800";
  }
  if (["infrastructure", "cancelled", "llm_failure"].includes(key)) {
    return "bg-sky-950 text-sky-300 border-sky-800";
  }
  return "bg-zinc-800 text-zinc-300 border-zinc-700";
};

export function StatusPill({ value }: { value: string }) {
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] uppercase tracking-wide ${toneFor(value)}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
