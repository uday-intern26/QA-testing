"use client";

import { useState } from "react";
import { api, FrameRow } from "@/lib/api";
import { EarlobeOverlay } from "./EarlobeOverlay";
import { StatusBadge } from "./StatusBadge";

interface Props {
  frame: FrameRow | null;
  passThreshold: number;
  failThreshold: number;
  zoneYScale?: number;
  reference?: {
    imageUrl: string;
    earlobe: { x: number; y: number } | null;
    earring: { x: number; y: number } | null;
    earWidth: number;
    distance: number | null;
  } | null;
}

function formatPoint(point: { x: number; y: number } | null | undefined) {
  return point ? `${point.x.toFixed(4)}, ${point.y.toFixed(4)}` : "not measured";
}

function flag(value: boolean | null | undefined) {
  if (value === true) return "yes";
  if (value === false) return "no";
  return "unknown";
}

export function FrameViewer({ frame, passThreshold, failThreshold, zoneYScale = 1, reference }: Props) {
  const [showLandmarks, setShowLandmarks] = useState(true);
  const [showEarring, setShowEarring] = useState(true);
  const [showZone, setShowZone] = useState(true);
  const [showMeasurement, setShowMeasurement] = useState(true);
  const [annotated, setAnnotated] = useState(false);
  const [debugView, setDebugView] = useState(false);

  if (!frame) {
    return <p className="text-sm text-zinc-500">Select a frame to inspect the body and jewelry anchors.</p>;
  }

  const validation = frame.landmark_validation;
  const diagnostics = frame.jewelry_diagnostics;
  const anchorSource = validation?.anchor_source || diagnostics?.anchor_source;
  const debugAvailable = Boolean(frame.debug_image_url);
  const showDebug = debugView && debugAvailable;
  const image = showDebug
    ? (frame.debug_image_url as string)
    : annotated && frame.annotated_image_url
      ? frame.annotated_image_url
      : frame.image_url;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div>
        <div className="relative inline-block max-w-full overflow-hidden rounded border border-zinc-800 bg-black">
          <img src={api.asset(image)} alt={`Frame ${frame.frame_number}`} className="max-h-[520px] w-full object-contain" />
          {!annotated && !showDebug ? (
            <EarlobeOverlay
              earlobe={frame.earlobe}
              earring={frame.earring}
              earWidth={frame.zone?.ear_width || 0.05}
              zoneYScale={zoneYScale}
              passThreshold={passThreshold}
              failThreshold={failThreshold}
              normalizedDistance={
                validation?.position_error_normalized ?? frame.normalized_distance
              }
              showLandmarks={showLandmarks}
              showEarring={showEarring}
              showZone={showZone}
              showMeasurement={showMeasurement}
              landmarksUrl={frame.landmarks_url}
              side={frame.side}
            />
          ) : null}
        </div>
        <div className="mt-3 flex flex-wrap gap-3 text-sm text-zinc-300">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={showLandmarks} onChange={(event) => setShowLandmarks(event.target.checked)} />
            Show landmarks
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={showEarring} onChange={(event) => setShowEarring(event.target.checked)} />
            Show jewelry anchor
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={showZone} onChange={(event) => setShowZone(event.target.checked)} />
            Show placement zone
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={showMeasurement} onChange={(event) => setShowMeasurement(event.target.checked)} />
            Show measurement
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={annotated} onChange={(event) => setAnnotated(event.target.checked)} />
            Server annotated image
          </label>
          <label className={`flex items-center gap-2 ${debugAvailable ? "" : "opacity-40"}`}>
            <input
              type="checkbox"
              checked={showDebug}
              disabled={!debugAvailable}
              onChange={(event) => setDebugView(event.target.checked)}
            />
            Landmark debug view
            {debugAvailable ? null : <span className="text-xs text-zinc-500">(run with Debug Mode on)</span>}
          </label>
        </div>
        {reference?.imageUrl ? (
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            <figure>
              <figcaption className="mb-2 text-xs uppercase tracking-wide text-zinc-500">Reference</figcaption>
              <div className="relative overflow-hidden rounded border border-zinc-800">
                <img src={reference.imageUrl} alt="Reference" className="w-full object-contain" />
                <EarlobeOverlay
                  earlobe={reference.earlobe}
                  earring={reference.earring}
                  earWidth={reference.earWidth || 0.05}
                  zoneYScale={zoneYScale}
                  passThreshold={passThreshold}
                  failThreshold={failThreshold}
                  normalizedDistance={reference.distance}
                  showLandmarks
                  showEarring
                  showZone={false}
                  showMeasurement
                />
              </div>
              <p className="mt-2 text-sm text-zinc-400">Reference distance: {reference.distance?.toFixed(3) ?? "n/a"}</p>
            </figure>
            <figure>
              <figcaption className="mb-2 text-xs uppercase tracking-wide text-zinc-500">Actual</figcaption>
              <div className="relative overflow-hidden rounded border border-zinc-800">
                <img src={api.asset(frame.image_url)} alt="Actual frame" className="w-full object-contain" />
                <EarlobeOverlay
                  earlobe={frame.earlobe}
                  earring={frame.earring}
                  earWidth={frame.zone?.ear_width || 0.05}
                  zoneYScale={zoneYScale}
                  passThreshold={passThreshold}
                  failThreshold={failThreshold}
                  normalizedDistance={frame.normalized_distance}
                  showLandmarks={showLandmarks}
                  showEarring={showEarring}
                  showZone={showZone}
                  showMeasurement={showMeasurement}
                />
              </div>
              <p className="mt-2 text-sm text-zinc-300">Actual distance: {frame.normalized_distance?.toFixed(3) ?? "n/a"}</p>
              <p className="text-sm text-zinc-300">
                Difference:{" "}
                {frame.normalized_distance != null && reference.distance != null
                  ? (frame.normalized_distance - reference.distance).toFixed(3)
                  : "n/a"}
              </p>
            </figure>
          </div>
        ) : null}
      </div>
      <aside className="space-y-2 rounded border border-zinc-800 bg-zinc-950 p-4 text-sm">
        <p className="text-zinc-400">Frame {String(frame.frame_number).padStart(3, "0")}</p>
        <p>Timestamp: {(frame.timestamp_ms / 1000).toFixed(1)}s</p>
        <p className="capitalize">Category: {frame.jewelry_category || "n/a"}</p>
        <p>Side: {frame.side}</p>
        <p>
          Body parts:{" "}
          {(frame.detected_body_parts && frame.detected_body_parts.length
            ? frame.detected_body_parts.join(", ")
            : "n/a")}
        </p>
        {frame.required_body_parts?.length ? (
          <p className="text-zinc-500">Required: {frame.required_body_parts.join(", ")}</p>
        ) : null}
        <p>
          Body detection confidence:{" "}
          {frame.body_confidence != null
            ? frame.body_confidence.toFixed(2)
            : frame.earlobe_confidence?.toFixed(2) ?? "n/a"}
        </p>
        <p>
          Jewelry detection confidence:{" "}
          {frame.earring_detected && frame.earring_confidence != null
            ? frame.earring_confidence.toFixed(2)
            : "not measured"}
          {anchorSource ? <span className="text-zinc-500"> ({anchorSource})</span> : null}
        </p>
        <p>
          Jewelry:{" "}
          {frame.earring_detected ? "detected" : "not detected"}
          {!frame.earring_detected && diagnostics?.anchor_stage ? (
            <span className="text-zinc-500"> · {diagnostics.anchor_stage}</span>
          ) : null}
        </p>
        <p>Frame quality: {frame.frame_quality_score != null ? frame.frame_quality_score.toFixed(2) : "n/a"}</p>
        <p className="capitalize">Selection: {frame.selection_status || "selected"}</p>
        {frame.rejection_reasons?.length ? (
          <div className="space-y-1 text-amber-400/90">
            <p className="text-xs uppercase tracking-wide text-amber-500/80">
              {frame.selection_status === "selected" ? "Selection notes (not placement failures)" : "Rejection"}
            </p>
            {frame.rejection_reasons.map((reason) => {
              const source = frame.rejection_sources?.[reason] || "unknown stage";
              const isDuplicate = reason === "near_duplicate" || source === "duplicate_filter";
              return (
                <p key={reason} className="text-sm">
                  {reason} ({source})
                  {isDuplicate && frame.selection_status === "selected"
                    ? " — frame kept; duplicate filtering is not a jewelry placement failure"
                    : null}
                </p>
              );
            })}
          </div>
        ) : null}

        <div className="mt-2 space-y-1 rounded border border-zinc-800 bg-zinc-900/50 p-2">
          <p className="text-xs uppercase tracking-wide text-zinc-500">Placement measurement</p>
          <p>Expected X/Y: {formatPoint(validation?.expected ?? frame.earlobe)}</p>
          <p>Actual X/Y: {formatPoint(validation?.actual ?? frame.earring)}</p>
          <p>
            Distance:{" "}
            {validation?.position_error_px != null
              ? `${validation.position_error_px.toFixed(2)} px`
              : frame.earring_detected
                ? "n/a"
                : "not measured (no jewelry anchor)"}
          </p>
          <p>
            Normalized distance:{" "}
            {validation?.position_error_normalized != null
              ? validation.position_error_normalized.toFixed(4)
              : frame.normalized_distance != null
                ? frame.normalized_distance.toFixed(4)
                : frame.earring_detected
                  ? "n/a"
                  : "not measured (no jewelry anchor)"}
          </p>
          <p>
            Allowed tolerance: &lt;={" "}
            {validation?.checks?.position?.tolerance?.toFixed(4) ?? failThreshold.toFixed(4)} normalized
          </p>
          <p>
            Result: <StatusBadge status={validation?.status || frame.automated_result} />
          </p>
          {(frame.failure_reason || validation?.failure_reason) ? (
            <p className="font-mono text-xs text-red-400">
              {frame.failure_reason || validation?.failure_reason}
            </p>
          ) : null}
        </div>

        {diagnostics && !frame.earring_detected ? (
          <div className="mt-2 space-y-1 rounded border border-amber-900/60 bg-amber-950/20 p-2 text-xs">
            <p className="uppercase tracking-wide text-amber-400">Why no jewelry anchor</p>
            <p className="font-mono text-amber-300">{diagnostics.anchor_stage || "NO_DEBUG_STATE"}</p>
            <p className="text-zinc-400">Anchor source: {diagnostics.anchor_source || "unavailable"}</p>
            <p className="text-zinc-400">GLB loaded: {flag(diagnostics.glb_loaded)}</p>
            <p className="text-zinc-400">Mesh visible: {flag(diagnostics.mesh_visible)}</p>
            <p className="text-zinc-400">Transform computed: {flag(diagnostics.transform_computed)}</p>
            <p className="text-zinc-400">Anchor projected: {flag(diagnostics.anchor_projected)}</p>
            {diagnostics.notes?.length ? (
              <p className="text-zinc-500">Notes: {diagnostics.notes.join(", ")}</p>
            ) : null}
          </div>
        ) : null}
        <p className="pt-2">
          <StatusBadge status={frame.automated_result} />
        </p>
        <p className="text-zinc-300">{frame.reason}</p>
        {frame.manual_result ? (
          <p className="text-zinc-400">
            Manual review {frame.manual_result} by {frame.reviewer}. Automated result stays {frame.automated_result}.{" "}
            {frame.review_reason}
          </p>
        ) : null}
      </aside>
    </div>
  );
}
