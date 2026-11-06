"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

type RunRow = Record<string, string | null>;

export default function ResultsPage() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    return api.runs()
      .then((items) => setRuns(items as RunRow[]))
      .catch((exc: Error) => setError(exc.message));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const finished = runs.filter((run) => run.overall_status);

  async function removeRun(runId: string) {
    if (!window.confirm(`Delete result ${runId}?`)) return;
    setBusy(true);
    setError("");
    try {
      await api.deleteRun(runId);
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  async function clearAll() {
    if (!window.confirm("Clear all latest results and run history?")) return;
    setBusy(true);
    setError("");
    try {
      await api.clearHistory();
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Clear failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold">Latest Results</h2>
        <button
          type="button"
          disabled={busy || finished.length === 0}
          onClick={() => void clearAll()}
          className="rounded border border-red-900 px-3 py-1.5 text-sm text-red-300 hover:bg-red-950 disabled:opacity-40"
        >
          Clear all
        </button>
      </div>
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      <ul className="space-y-3">
        {finished.map((run) => (
          <li key={String(run.test_run_id)} className="rounded border border-zinc-800 p-4">
            <div className="flex items-center justify-between gap-3">
              <Link className="underline" href={`/tests/${run.test_id}`}>
                {run.test_name}
              </Link>
              <div className="flex items-center gap-3">
                <StatusBadge status={run.overall_status} />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void removeRun(String(run.test_run_id))}
                  className="rounded border border-red-900 px-2 py-1 text-xs text-red-300 hover:bg-red-950 disabled:opacity-40"
                >
                  Delete
                </button>
              </div>
            </div>
            <p className="mt-1 text-xs text-zinc-500">{run.test_run_id}</p>
          </li>
        ))}
        {!finished.length ? <li className="text-sm text-zinc-500">No finished runs yet.</li> : null}
      </ul>
    </div>
  );
}
