"use client";

import { useState } from "react";
import { LandmarkCheck, LandmarkSideSummary, QaReport } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

const CHECK_LABELS: Record<string, string> = {
  landmark_detection: "Landmark detection",
  visibility: "Visibility",
  position: "Attachment position",
  rotation: "Rotation",
  scale: "Scale",
  temporal_stability: "Temporal stability",
};

function num(value: number | null | undefined, digits = 2, suffix = "") {
  return value === null || value === undefined ? "—" : `${value.toFixed(digits)}${suffix}`;
}

export function LandmarkValidationPanel({ report }: { report: QaReport }) {
  const validation = report.landmark_validation;
  const [expanded, setExpanded] = useState<string | null>(null);
  if (!validation) return null;

  const sides = Object.entries(validation.sides || {});

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">Landmark validation</p>
          <h3 className="mt-1 text-lg font-medium text-zinc-100">
            {validation.profile?.label || report.jewelry_type} · attachment on the{" "}
            {validation.profile?.body_region}
          </h3>
          <p className="mt-1 text-xs text-zinc-500">
            Debug Mode {validation.debug_mode ? "on" : "off"} ·{" "}
            {validation.enforced
              ? "landmark results decide the verdict"
              : "landmark results are reported only"}
          </p>
        </div>
        <div className="text-right">
          <StatusBadge status={validation.overall_status} />
          {validation.failure_reason ? (
            <p className="mt-1 font-mono text-xs text-red-400">{validation.failure_reason}</p>
          ) : null}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {sides.map(([side, summary]) => (
          <SideCard
            key={side}
            side={side}
            summary={summary}
            expanded={expanded === side}
            onToggle={() => setExpanded(expanded === side ? null : side)}
          />
        ))}
      </div>
    </div>
  );
}

const ANCHOR_SOURCE_LABELS: Record<string, string> = {
  debug_bridge: "page QA bridge",
  scene_probe: "live Three.js scene",
  blob: "pixel fallback",
  template: "template match",
  missing: "no anchor found",
};

function AnchorOrigins({
  sources,
  stages,
}: {
  sources?: Record<string, number> | null;
  stages?: Record<string, number> | null;
}) {
  const sourceEntries = Object.entries(sources || {});
  const stageEntries = Object.entries(stages || {});
  if (!sourceEntries.length && !stageEntries.length) return null;
  return (
    <div className="mt-3 rounded border border-zinc-800 bg-zinc-900/40 px-2 py-2 text-[11px]">
      <p className="text-zinc-500">Where the actual coordinates came from</p>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-zinc-300">
        {sourceEntries.map(([name, count]) => (
          <span key={name}>
            {ANCHOR_SOURCE_LABELS[name] || name}: {count}
          </span>
        ))}
      </div>
      {stageEntries.length ? (
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-amber-400/80">
          {stageEntries.map(([stage, count]) => (
            <span key={stage}>
              {stage} × {count}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SideCard({
  side,
  summary,
  expanded,
  onToggle,
}: {
  side: string;
  summary: LandmarkSideSummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const metrics = summary.metrics;
  return (
    <div className="rounded border border-zinc-800 px-3 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-zinc-200 capitalize">{side}</p>
        <StatusBadge status={summary.overall_status} />
      </div>
      {summary.failure_reason ? (
        <p className="mt-1 font-mono text-xs text-red-400">{summary.failure_reason}</p>
      ) : null}

      <dl className="mt-3 space-y-1 text-xs">
        {Object.entries(summary.checks || {}).map(([name, check]: [string, LandmarkCheck]) => (
          <div key={name} className="flex items-start justify-between gap-3">
            <dt className="text-zinc-500">{CHECK_LABELS[name] || name}</dt>
            <dd className="text-right text-zinc-300">
              <span
                className={
                  check.status === "PASS"
                    ? "text-emerald-400"
                    : check.status === "FAIL"
                      ? "text-red-400"
                      : "text-amber-400"
                }
              >
                {check.status}
              </span>
            </dd>
          </div>
        ))}
      </dl>

      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-zinc-400">
        <span>
          Valid frames: {metrics.valid_frames}/{metrics.total_frames}
        </span>
        <span>Ignored frames: {metrics.ignored_frames}</span>
        <span>Avg error: {num(metrics.average_position_error_px, 2, " px")}</span>
        <span>Max error: {num(metrics.max_position_error_px, 2, " px")}</span>
        <span>Avg normalized: {num(metrics.average_position_error_normalized, 4)}</span>
        <span>Allowed: {num(summary.tolerances?.position_tolerance_normalized, 4)}</span>
        <span>Tracking failures: {metrics.tracking_failures}</span>
        <span>Max consecutive: {metrics.max_consecutive_failures}</span>
      </div>

      <AnchorOrigins sources={summary.anchor_sources} stages={summary.anchor_stages} />

      <button type="button" className="mt-3 text-xs text-zinc-400 underline" onClick={onToggle}>
        {expanded ? "Hide" : "Show"} frame-by-frame data
      </button>

      {expanded ? (
        <div className="mt-2 max-h-64 overflow-auto rounded border border-zinc-800">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-zinc-900 text-zinc-500">
              <tr>
                <th className="px-2 py-1">Frame</th>
                <th className="px-2 py-1">Expected</th>
                <th className="px-2 py-1">Actual</th>
                <th className="px-2 py-1">Error px</th>
                <th className="px-2 py-1">Normalized</th>
                <th className="px-2 py-1">Anchor from</th>
                <th className="px-2 py-1">Status</th>
              </tr>
            </thead>
            <tbody>
              {summary.frames.map((frame) => (
                <tr key={frame.frame_number} className="border-t border-zinc-900">
                  <td className="px-2 py-1 text-zinc-300">{frame.frame_number}</td>
                  <td className="px-2 py-1 text-zinc-400">
                    {frame.expected_px
                      ? `${frame.expected_px[0].toFixed(0)}, ${frame.expected_px[1].toFixed(0)}`
                      : "—"}
                  </td>
                  <td className="px-2 py-1 text-zinc-400">
                    {frame.actual_px ? `${frame.actual_px[0].toFixed(0)}, ${frame.actual_px[1].toFixed(0)}` : "—"}
                  </td>
                  <td className="px-2 py-1 text-zinc-400">{num(frame.position_error_px)}</td>
                  <td className="px-2 py-1 text-zinc-400">{num(frame.position_error_normalized, 4)}</td>
                  <td
                    className="px-2 py-1 font-mono text-[10px] text-zinc-500"
                    title={frame.diagnostics?.anchor_stage || undefined}
                  >
                    {frame.anchor_source || "—"}
                  </td>
                  <td className="px-2 py-1">
                    <span
                      className={
                        frame.status === "PASS"
                          ? "text-emerald-400"
                          : frame.status === "FAIL"
                            ? "text-red-400"
                            : "text-amber-400"
                      }
                      title={frame.failure_reason || undefined}
                    >
                      {frame.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
