"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { api, FrameRow, QaReport, TestRecord } from "@/lib/api";
import { BackButton } from "@/components/BackButton";
import { CapturedFrameGallery } from "@/components/CapturedFrameGallery";
import { FrameViewer } from "@/components/FrameViewer";
import { LandmarkValidationPanel } from "@/components/LandmarkValidationPanel";
import { PlacementResult } from "@/components/PlacementResult";
import { StatusBadge } from "@/components/StatusBadge";

type FrameFilter = "all" | "FAIL" | "WARNING" | "PASS" | "NOT_TESTABLE";

export default function TestDetailPage() {
  const params = useParams<{ id: string }>();
  const [test, setTest] = useState<TestRecord | null>(null);
  const [report, setReport] = useState<QaReport | null>(null);
  const [active, setActive] = useState<FrameRow | null>(null);
  const [error, setError] = useState("");
  const [resultsError, setResultsError] = useState("");
  const [frameFilter, setFrameFilter] = useState<FrameFilter>("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const id = params.id;
    setLoading(true);
    setError("");
    setResultsError("");
    api
      .getTest(id)
      .then(setTest)
      .catch((exc: Error) => setError(exc.message));
    api
      .results(id)
      .then((result) => {
        setReport(result);
        setActive(result.frames.find((frame) => frame.status === "FAIL") || result.frames[0] || null);
      })
      .catch((exc: Error) => {
        setReport(null);
        setResultsError(exc.message || "No completed results for this test.");
      })
      .finally(() => setLoading(false));
  }, [params.id]);

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

  function selectFrame(frame: FrameRow) {
    setActive(frame);
    window.setTimeout(() => {
      document.getElementById("selected-frame-result")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }, 30);
  }

  const title = test?.name || report?.test_name || params.id;
  const stats = report?.statistics;
  const passRate =
    stats != null ? `${(stats.pass_percentage ?? stats.pass_rate * 100).toFixed(1)}%` : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <BackButton label="Back" />
          <div>
            <h2 className="text-2xl font-semibold">{title}</h2>
            {report ? (
              <p className="mt-1 text-sm text-zinc-400">
                {report.jewelry_type}
                {report.jewelry_id ? ` · ${report.jewelry_id}` : ""}
                {report.test_run_id ? ` · ${report.test_run_id}` : ""}
              </p>
            ) : null}
          </div>
        </div>
        {report ? <StatusBadge status={report.overall_status} /> : null}
      </div>

      {error && !report ? <p className="text-sm text-red-400">{error}</p> : null}
      {loading ? <p className="text-sm text-zinc-500">Loading results…</p> : null}

      {report ? (
        <>
          <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            <SimpleMetric label="Pass rate" value={passRate || "n/a"} />
            <SimpleMetric label="Passed" value={String(stats?.frames_passed ?? 0)} />
            <SimpleMetric label="Failed" value={String(stats?.frames_failed ?? 0)} />
            <SimpleMetric
              label="Frames tested"
              value={String(stats?.testable_frames ?? stats?.frames_selected ?? 0)}
            />
          </div>
          {report.reason ? <p className="text-sm text-zinc-300">{report.reason}</p> : null}

          <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            <SimpleMetric label="Frames captured" value={String(stats?.frames_captured ?? 0)} />
            <SimpleMetric label="Minimum required" value={String(stats?.minimum_required_frames ?? 30)} />
            <SimpleMetric label="Usable frames" value={String(stats?.frames_usable ?? stats?.frames_analyzed ?? 0)} />
            <SimpleMetric label="Rejected frames" value={String(stats?.frames_rejected ?? 0)} />
          </div>
          <p className="text-xs text-zinc-500">
            Frame count starts after the jewelry is placed on the body. Target {stats?.target_frames ?? 40}. Near-pass labels do not change PASS or FAIL.
          </p>
          {report.layers ? (
            <div className="grid gap-2 text-sm md:grid-cols-3">
              <LayerLine title="Layer 1 · Frame selection" value={report.layers.frame_selection} />
              <LayerLine title="Layer 2 · Anchors" value={report.layers.anchor_detection} />
              <LayerLine title="Layer 3 · Placement" value={report.layers.placement_validation} />
            </div>
          ) : null}
          {report.closest_frames && report.closest_frames.length > 0 ? (
            <div className="rounded border border-zinc-800 p-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">Frames closest to pass</h3>
              <div className="mt-2 space-y-2">
                {report.closest_frames.map((frame) => (
                  <div key={`${frame.frame_number}-${frame.review_label}`} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                    <span>
                      Frame {frame.frame_number} · {frame.review_label === "NEAR_PASS" ? "Near pass" : frame.review_label}
                    </span>
                    <span className="text-zinc-400">
                      Measured {frame.normalized_distance?.toFixed(3) ?? "n/a"} · threshold {frame.pass_threshold.toFixed(3)} · gap {frame.placement_gap?.toFixed(3) ?? "n/a"}
                    </span>
                    <StatusBadge status={frame.status} />
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">Frame results</h3>
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
            <div className="mb-6">
              <CapturedFrameGallery report={report} active={active} onSelect={selectFrame} />
            </div>
            {active ? (
              <div id="selected-frame-result" className="mb-6 scroll-mt-4">
                <FrameViewer
                  frame={active}
                  passThreshold={report.thresholds.pass_threshold}
                  failThreshold={report.thresholds.fail_threshold}
                  zoneYScale={report.thresholds.zone_y_scale || 1}
                />
              </div>
            ) : null}
            <div className="mb-6">
              <LandmarkValidationPanel report={report} />
            </div>
            <PlacementResult
              frames={visibleFrames}
              activeId={active?.frame_id}
              activeSide={active?.side}
              onSelect={selectFrame}
            />
          </div>
        </>
      ) : !loading ? (
        <div className="space-y-2">
          <BackButton label="Back" />
          <p className="text-sm text-zinc-500">{resultsError || "This test has no completed results yet."}</p>
        </div>
      ) : null}
    </div>
  );
}

function LayerLine({
  title,
  value,
}: {
  title: string;
  value: { status: string; detail: string } | string | undefined;
}) {
  const status = !value ? "NOT_RUN" : typeof value === "string" ? value : value.status;
  const detail = !value || typeof value === "string" ? "" : value.detail;
  return (
    <div className="rounded border border-zinc-800 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs uppercase tracking-wide text-zinc-500">{title}</p>
        <StatusBadge status={status} />
      </div>
      {detail ? <p className="mt-1 text-xs text-zinc-400">{detail}</p> : null}
    </div>
  );
}

function SimpleMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-zinc-800 px-3 py-2">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-lg font-medium text-zinc-100">{value}</p>
    </div>
  );
}
