"use client";

import { useMemo, useState } from "react";
import { api, FrameRow, QaReport } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

function onePerFrame(frames: FrameRow[]) {
  const byId = new Map<string, FrameRow>();
  for (const frame of frames) {
    const current = byId.get(frame.frame_id);
    if (!current) {
      byId.set(frame.frame_id, frame);
      continue;
    }
    const nextScore = frame.matching_score ?? -1;
    const currentScore = current.matching_score ?? -1;
    if (nextScore > currentScore) byId.set(frame.frame_id, frame);
  }
  return Array.from(byId.values());
}

function seconds(timestampMs: number | null | undefined) {
  if (timestampMs == null) return "n/a";
  return `${(timestampMs / 1000).toFixed(1)}s`;
}

function FrameShot({
  frame,
  className,
}: {
  frame: FrameRow;
  className: string;
}) {
  const [failed, setFailed] = useState(false);
  const src = api.asset(frame.image_url);
  if (!src || failed) {
    return (
      <div className={`${className} flex items-center justify-center bg-zinc-900 px-2 text-center text-xs text-zinc-500`}>
        Frame {String(frame.frame_number).padStart(3, "0")} has no image
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={`Frame ${frame.frame_number}`}
      className={className}
      onError={() => setFailed(true)}
    />
  );
}

export function CapturedFrameGallery({
  report,
  active,
  onSelect,
}: {
  report: QaReport;
  active?: FrameRow | null;
  onSelect: (frame: FrameRow) => void;
}) {
  const frames = report.frames || [];
  const stats = report.statistics;
  const unique = useMemo(() => onePerFrame(frames), [frames]);
  const ranked = useMemo(
    () => [...unique].sort((a, b) => (a.placement_rank ?? 9999) - (b.placement_rank ?? 9999)),
    [unique]
  );
  const top = ranked.filter((frame) => frame.top_match).slice(0, 5);
  const shownTop = top.length ? top : ranked.slice(0, 5);
  const timeline = useMemo(
    () => [...unique].sort((a, b) => a.timestamp_ms - b.timestamp_ms || a.frame_number - b.frame_number),
    [unique]
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
        <Metric label="Frames captured" value={String(stats?.frames_captured ?? unique.length)} />
        <Metric label="Detected frames" value={String(stats?.frames_detected ?? unique.length)} />
        <Metric label="Valid tracing points" value={String(stats?.frames_with_tracing_points ?? 0)} />
        <Metric
          label="Average accuracy"
          value={stats?.average_tracing_accuracy == null ? "n/a" : `${stats.average_tracing_accuracy.toFixed(1)}%`}
        />
      </div>
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">Best 5 matches</h3>
        <p className="mt-1 text-xs text-zinc-500">
          Ranked by jewelry-to-body tracing distance. The closest placement is highlighted.
        </p>
        {shownTop.length ? (
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {shownTop.map((frame) => (
              <FrameCard key={frame.frame_id} frame={frame} active={active} onSelect={onSelect} emphasize />
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm text-zinc-500">No scored frames were stored for this run.</p>
        )}
      </div>
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">All captured frames</h3>
        <p className="mt-1 text-xs text-zinc-500">{timeline.length} frames, in capture order.</p>
        {timeline.length ? (
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {timeline.map((frame) => (
              <FrameCard key={`all-${frame.frame_id}`} frame={frame} active={active} onSelect={onSelect} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function FrameCard({
  frame,
  active,
  onSelect,
  emphasize = false,
}: {
  frame: FrameRow;
  active?: FrameRow | null;
  onSelect: (frame: FrameRow) => void;
  emphasize?: boolean;
}) {
  const selected = active?.frame_id === frame.frame_id;
  const best = Boolean(frame.best_match);
  return (
    <button
      type="button"
      onClick={() => onSelect(frame)}
      className={`overflow-hidden rounded-lg border text-left ${
        best
          ? "border-amber-300"
          : selected
            ? "border-zinc-200"
            : "border-zinc-800 hover:border-zinc-600"
      }`}
    >
      <FrameShot frame={frame} className={emphasize ? "h-36 w-full object-cover" : "h-40 w-full object-cover"} />
      <div className="space-y-1 p-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-zinc-200">
            Frame {String(frame.frame_number).padStart(3, "0")}
            {best ? " · Best match" : frame.top_match ? ` · Rank ${frame.placement_rank}` : ""}
          </p>
          <StatusBadge status={frame.status} />
        </div>
        <p className="text-xs text-zinc-400">
          {seconds(frame.timestamp_ms)}
          {frame.placement_accuracy != null ? ` · ${frame.placement_accuracy.toFixed(1)}% match` : ""}
          {frame.normalized_distance != null ? ` · distance ${frame.normalized_distance.toFixed(3)}` : ""}
        </p>
      </div>
    </button>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-950 px-3 py-2">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-xl text-zinc-100">{value}</p>
    </div>
  );
}
