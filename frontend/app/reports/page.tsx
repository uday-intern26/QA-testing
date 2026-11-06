"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

type RunRow = Record<string, string | null>;

export default function ReportsPage() {
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
    if (!window.confirm(`Delete report for ${runId}?`)) return;
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
    if (!window.confirm("Clear all reports and run history?")) return;
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
        <div>
          <h2 className="text-2xl font-semibold">Reports</h2>
          <p className="mt-1 text-sm text-zinc-400">
            Download the JSON report for any completed run. Geometry, not pixel similarity, is the source of truth.
          </p>
        </div>
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
          <li key={String(run.test_run_id)} className="flex items-center justify-between rounded border border-zinc-800 p-4">
            <div>
              <Link className="underline" href={`/tests/${run.test_id}`}>
                {run.test_name}
              </Link>
              <p className="mt-1 text-xs text-zinc-500">{run.test_run_id}</p>
            </div>
            <div className="flex items-center gap-3">
              <StatusBadge status={run.overall_status} />
              <a className="text-sm underline" href={api.reportUrl(String(run.test_id))}>
                Download
              </a>
              <button
                type="button"
                disabled={busy}
                onClick={() => void removeRun(String(run.test_run_id))}
                className="rounded border border-red-900 px-2 py-1 text-xs text-red-300 hover:bg-red-950 disabled:opacity-40"
              >
                Delete
              </button>
            </div>
          </li>
        ))}
        {!finished.length ? <li className="text-sm text-zinc-500">No reports yet.</li> : null}
      </ul>
    </div>
  );
}
