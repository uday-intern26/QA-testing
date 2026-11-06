"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useState } from "react";

import { Card } from "@/components/Shell";
import { StatusPill } from "@/components/agentic/StatusPill";
import { agenticApi } from "@/lib/agentic/api";
import type { ExecutionResult, Report, RunRecord } from "@/lib/agentic/types";

function count(summary: RunRecord["summary"], key: "passed" | "failed" | "blocked" | "needs_review" | "executed") {
  const value = summary?.[key];
  return typeof value === "number" ? value : "—";
}

export default function AgenticRunDetailPage() {
  const params = useParams<{ id: string }>();
  const runId = params.id;
  const [run, setRun] = useState<RunRecord | null>(null);
  const [results, setResults] = useState<ExecutionResult[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;

    const load = async () => {
      try {
        const nextRun = await agenticApi<RunRecord>(`/qa/runs/${runId}`);
        if (cancelled) return;
        setRun(nextRun);
        if (nextRun.status === "queued" || nextRun.status === "running") {
          timer = window.setTimeout(load, 2000);
          return;
        }
        const [nextResults, nextReport] = await Promise.all([
          agenticApi<{ results: ExecutionResult[] }>(`/qa/runs/${runId}/results`),
          agenticApi<Report>(`/qa/runs/${runId}/report`),
        ]);
        if (cancelled) return;
        setResults(nextResults.results);
        setReport(nextReport);
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load the run");
      }
    };

    load();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [runId]);

  async function cancel() {
    try {
      const updated = await agenticApi<{ status: string }>(`/qa/runs/${runId}/cancel`, { method: "POST" });
      setRun((current) => (current ? { ...current, status: updated.status } : current));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Cancel failed");
    }
  }

  const visible = results.filter((item) => filter === "all" || item.status === filter);
  const coverage = report?.api_coverage?.percent ?? 0;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Agentic QA · Run</p>
          <h2 className="mt-1 font-mono text-2xl font-semibold text-zinc-100">{runId}</h2>
          <p className="mt-2 text-sm text-zinc-400">
            {run ? `${run.service} · ${run.tenant} · ${run.model_version}` : "Loading the stored run."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/agentic/runs" className="rounded border border-zinc-700 px-3 py-2 text-sm text-zinc-300">
            Back
          </Link>
          {run && (run.status === "queued" || run.status === "running") ? (
            <button type="button" onClick={cancel} className="rounded bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-950">
              Cancel
            </button>
          ) : null}
          <a
            href={`/api/agentic/qa/runs/${runId}/report?format=html`}
            target="_blank"
            rel="noreferrer"
            className="rounded border border-zinc-700 px-3 py-2 text-sm text-zinc-300"
          >
            HTML report
          </a>
        </div>
      </header>

      {error ? <div className="rounded border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-200">{error}</div> : null}

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <div className="mb-2">{run ? <StatusPill value={run.status} /> : "—"}</div>
          <p className="font-mono text-xs text-zinc-500">{run?.target_url ?? ""}</p>
        </Card>
        <Card>
          <p className="text-2xl font-semibold">{count(run?.summary ?? null, "passed")}</p>
          <p className="mt-1 text-xs text-zinc-500">Passed</p>
        </Card>
        <Card>
          <p className="text-2xl font-semibold">{count(run?.summary ?? null, "failed")}</p>
          <p className="mt-1 text-xs text-zinc-500">Failed</p>
        </Card>
        <Card>
          <p className="text-2xl font-semibold">{count(run?.summary ?? null, "executed")}</p>
          <p className="mt-1 text-xs text-zinc-500">Executed</p>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`API coverage ${coverage}%`}>
          <div className="mb-3 h-2 overflow-hidden rounded-full bg-zinc-800">
            <div className="h-full bg-zinc-300" style={{ width: `${Math.max(0, Math.min(100, coverage))}%` }} />
          </div>
          <p className="mb-3 text-xs text-zinc-500">
            {report?.api_coverage
              ? `${report.api_coverage.operations_exercised} of ${report.api_coverage.operations_total} operations`
              : "Coverage appears after the run completes."}
          </p>
          <div className="space-y-1 font-mono text-xs text-zinc-400">
            {report?.api_coverage?.exercised.map((item) => (
              <div key={item}>{item}</div>
            ))}
          </div>
        </Card>

        <Card title="Quality and isolation">
          <p className="mb-3 text-sm text-zinc-400">
            Tenant isolation: {report?.tenant_isolation?.passed ?? 0} passed, {report?.tenant_isolation?.failed ?? 0} failed.
            Latency p50 {report?.latency_ms?.p50 ?? "—"} ms.
          </p>
          <div className="space-y-2 text-sm">
            {Object.entries(report?.model_quality ?? {}).map(([name, metric]) => {
              const shown =
                metric.available && metric.value !== null
                  ? `${Number.isInteger(metric.value) ? metric.value : metric.value.toFixed(2)} ${metric.unit ?? ""}`.trim()
                  : metric.detail;
              return (
                <div key={name}>
                  <strong className="text-zinc-200">{name.replaceAll("_", " ")}</strong>
                  <div className="text-xs text-zinc-500">{shown}</div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      <Card>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h3 className="mr-2 text-sm font-semibold uppercase tracking-wide text-zinc-300">Results</h3>
          {["all", "passed", "failed", "needs_review"].map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setFilter(value)}
              className={`rounded border px-3 py-1 text-xs ${
                filter === value ? "border-zinc-400 bg-zinc-800 text-zinc-100" : "border-zinc-700 text-zinc-400"
              }`}
            >
              {value}
            </button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="pb-2 pr-3">Test</th>
                <th className="pb-2 pr-3">Status</th>
                <th className="pb-2 pr-3">Class</th>
                <th className="pb-2 pr-3">HTTP</th>
                <th className="pb-2 pr-3">ms</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {visible.map((result) => (
                <Fragment key={result.execution_id}>
                  <tr className="border-t border-zinc-800">
                    <td className="py-2 pr-3 font-mono text-xs">{result.test_id}</td>
                    <td className="py-2 pr-3">
                      <StatusPill value={result.status} />
                    </td>
                    <td className="py-2 pr-3">
                      <StatusPill value={result.failure_class} />
                    </td>
                    <td className="py-2 pr-3">{result.http_status ?? "—"}</td>
                    <td className="py-2 pr-3">{result.latency_ms?.toFixed(1) ?? "—"}</td>
                    <td className="py-2">
                      <button
                        type="button"
                        className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300"
                        onClick={() => setOpen(open === result.execution_id ? null : result.execution_id)}
                      >
                        {open === result.execution_id ? "Hide" : "Invariants"}
                      </button>
                    </td>
                  </tr>
                  {open === result.execution_id ? (
                    <tr className="border-t border-zinc-900 bg-zinc-950/60">
                      <td colSpan={6} className="px-3 py-3 text-xs text-zinc-400">
                        {result.error ? <p className="mb-2 text-red-300">{result.error}</p> : null}
                        <div className="space-y-1">
                          {(result.invariants ?? []).map((item) => (
                            <div key={item.name}>
                              <StatusPill value={item.passed ? "passed" : "failed"} /> {item.name}
                              {item.detail ? <span> — {item.detail}</span> : null}
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {report?.recommendations?.length ? (
        <Card title="Recommendations">
          <ul className="list-disc space-y-1 pl-5 text-sm text-zinc-300">
            {report.recommendations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Card>
      ) : null}

      {report?.investigations?.length ? (
        <Card title="Investigations">
          <div className="space-y-4">
            {report.investigations.map((item) => (
              <div key={`${item.test_id}-${item.classification}`}>
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm">{item.test_id}</span>
                  <StatusPill value={item.classification || "unknown"} />
                </div>
                <p className="text-sm text-zinc-400">{item.recommended_action || item.summary}</p>
                {item.llm_note ? <p className="mt-1 text-xs text-zinc-500">Model note: {item.llm_note}</p> : null}
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
