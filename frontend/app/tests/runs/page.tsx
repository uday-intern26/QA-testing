"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

type RunRow = Record<string, string | number | null>;

export default function RunsPage() {
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

  async function removeRun(runId: string) {
    if (!window.confirm(`Delete run ${runId}? Results and reports for this run will be removed.`)) return;
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
    if (!window.confirm("Clear all Try-On QA run history, results, and reports? Applications and test configs are kept.")) {
      return;
    }
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
        <h2 className="text-2xl font-semibold">Test Runs</h2>
        <button
          type="button"
          disabled={busy || runs.length === 0}
          onClick={() => void clearAll()}
          className="rounded border border-red-900 px-3 py-1.5 text-sm text-red-300 hover:bg-red-950 disabled:opacity-40"
        >
          Clear all history
        </button>
      </div>
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-zinc-500">
          <tr>
            <th className="py-2">Run</th>
            <th>Test</th>
            <th>Status</th>
            <th>Result</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={String(run.test_run_id)} className="border-t border-zinc-800">
              <td className="py-2 font-mono text-xs">{run.test_run_id}</td>
              <td>
                <Link className="underline" href={`/tests/${run.test_id}`}>
                  {run.test_name}
                </Link>
              </td>
              <td>{run.status}</td>
              <td>
                <StatusBadge status={String(run.overall_status || "NOT_RUN")} />
              </td>
              <td className="py-2 text-right">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void removeRun(String(run.test_run_id))}
                  className="rounded border border-red-900 px-2 py-1 text-xs text-red-300 hover:bg-red-950 disabled:opacity-40"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!runs.length ? <p className="text-sm text-zinc-500">No test runs yet.</p> : null}
    </div>
  );
}
