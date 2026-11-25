"use client";

import { useEffect, useMemo, useState } from "react";
import { api, FrameRow, QaReport } from "@/lib/api";
import { CapturedFrameGallery } from "@/components/CapturedFrameGallery";
import { FrameViewer } from "@/components/FrameViewer";
import { PlacementResult } from "@/components/PlacementResult";
import { ResultSummary } from "@/components/ResultSummary";
import { StatusBadge } from "@/components/StatusBadge";

type FrameFilter = "all" | "FAIL" | "WARNING" | "PASS" | "NOT_TESTABLE";

export function TestRunResultsPanel({
  testId,
  onClose,
}: {
  testId: string;
  onClose?: () => void;
}) {
  const [report, setReport] = useState<QaReport | null>(null);
  const [active, setActive] = useState<FrameRow | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [frameFilter, setFrameFilter] = useState<FrameFilter>("all");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setReport(null);
    setActive(null);
    api
      .results(testId)
      .then((result) => {
        if (cancelled) return;
        setReport(result);
        setActive(result.frames.find((frame) => frame.status === "FAIL") || result.frames[0] || null);
      })
      .catch((exc: Error) => {
        if (!cancelled) setError(exc.message || "No completed results for this test.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [testId]);

  const frameCounts = useMemo(() => {
    const frames = report?.frames || [];
    return {
      all: frames.length,
      FAIL: frames.filter((frame) => frame.status === "FAIL").length,
      WARNING: frames.filter((frame) => frame.status === "WARNING").length,
      PASS: frames.filter((frame) => frame.status === "PASS").length,
      NOT_TESTABLE: frames.filter((frame) => frame.status === "NOT_TESTABLE").length,
    };
  }, [report]);

  const visibleFrames = useMemo(() => {
    if (!report) return [];
    if (frameFilter === "all") return report.frames;
    return report.frames.filter((frame) => frame.status === frameFilter);
  }, [report, frameFilter]);

  useEffect(() => {
    if (!visibleFrames.length) {
      setActive(null);
      return;
    }
    setActive((current) => {
      if (
        current &&
        visibleFrames.some((frame) => frame.frame_id === current.frame_id && frame.side === current.side)
      ) {
        return current;
      }
      return visibleFrames[0];
    });
  }, [visibleFrames]);

  return (
    <div className="space-y-5 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">Results in Test Runs</p>
          <h3 className="mt-1 text-lg font-semibold text-zinc-100">
            {report?.test_name || testId}
          </h3>
          {report ? (
            <p className="mt-1 text-sm text-zinc-400">
              Run {report.test_run_id} · {report.jewelry_type}
              {report.jewelry_id ? ` · ${report.jewelry_id}` : ""}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {report ? <StatusBadge status={report.overall_status} /> : null}
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
            >
              Close
            </button>
          ) : null}
        </div>
      </div>

      {loading ? <p className="text-sm text-zinc-500">Loading results…</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      {report ? (
        <>
          <ResultSummary report={report} />
          <div>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h4 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">Frame results</h4>
              <div className="flex flex-wrap gap-2">
                {(
                  [
                    ["all", "All frames"],
                    ["FAIL", "Failed"],
                    ["WARNING", "WARNING"],
                    ["PASS", "PASS"],
                    ["NOT_TESTABLE", "Not testable"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setFrameFilter(value)}
                    className={`rounded border px-2 py-1 text-xs ${
                      frameFilter === value ? "border-zinc-300 text-zinc-100" : "border-zinc-700 text-zinc-400"
                    }`}
                  >
                    {label} ({frameCounts[value]})
                  </button>
                ))}
              </div>
            </div>
            <p className="mb-3 text-xs text-zinc-500">
              Showing {visibleFrames.length} of {frameCounts.all} scored frames.
            </p>
            {report ? (
              <div className="mb-6">
                <CapturedFrameGallery report={report} active={active} onSelect={setActive} />
              </div>
            ) : null}
            <PlacementResult
              frames={visibleFrames}
              activeId={active?.frame_id}
              activeSide={active?.side}
              onSelect={setActive}
            />
            {active ? (
              <div className="mt-6">
                <FrameViewer
                  frame={active}
                  passThreshold={report.thresholds.pass_threshold}
                  failThreshold={report.thresholds.fail_threshold}
                  zoneYScale={report.thresholds.zone_y_scale || 1}
                />
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
