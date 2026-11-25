import { FrameRow } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

export function PlacementResult({
  frames,
  activeId,
  activeSide,
  onSelect,
}: {
  frames: FrameRow[];
  activeId?: string;
  activeSide?: string;
  onSelect: (frame: FrameRow) => void;
}) {
  if (!frames.length) {
    return <p className="text-sm text-zinc-500">No frame-level placement results.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-zinc-500">
          <tr>
            <th className="py-2">Frame</th>
            <th>Time</th>
            <th>Category</th>
            <th>Body part</th>
            <th>Body conf</th>
            <th>Jewelry conf</th>
            <th>Quality</th>
            <th>Selection</th>
            <th>Distance</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {frames.map((frame) => {
            const active = frame.frame_id === activeId && frame.side === activeSide;
            const bodyParts = (frame.detected_body_parts || []).join(", ") || (frame.earlobe_detected ? "body" : "—");
            const selection = frame.selection_status || (frame.status ? "selected" : "—");
            const placementReason =
              frame.failure_reason ||
              frame.landmark_validation?.failure_reason ||
              frame.reason ||
              null;
            const selectionNotes =
              frame.selection_status === "selected"
                ? (frame.rejection_reasons || [])
                    .filter((reason) => (frame.rejection_sources?.[reason] || "") !== "placement_validation")
                    .map((reason) => `${reason} (${frame.rejection_sources?.[reason] || "selection"})`)
                : frame.rejection_reasons || [];
            return (
              <tr
                key={`${frame.frame_id}-${frame.side}`}
                className={`cursor-pointer border-t border-zinc-800 ${
                  active ? "bg-zinc-800/70" : frame.status === "FAIL" ? "bg-red-950/40 hover:bg-red-950/60" : "hover:bg-zinc-900"
                }`}
                onClick={() => onSelect(frame)}
                title={
                  [placementReason, selectionNotes.length ? `Selection note: ${selectionNotes.join(", ")}` : null]
                    .filter(Boolean)
                    .join(" · ") || undefined
                }
              >
                <td className="py-2">{String(frame.frame_number).padStart(3, "0")}</td>
                <td>{(frame.timestamp_ms / 1000).toFixed(1)}s</td>
                <td className="capitalize">{frame.jewelry_category || "—"}</td>
                <td>{bodyParts}</td>
                <td>{frame.body_confidence != null ? frame.body_confidence.toFixed(2) : frame.earlobe_confidence?.toFixed(2) ?? "—"}</td>
                <td>
                  {frame.earring_detected && frame.earring_confidence != null
                    ? frame.earring_confidence.toFixed(2)
                    : "—"}
                </td>
                <td>{frame.frame_quality_score != null ? frame.frame_quality_score.toFixed(2) : "—"}</td>
                <td className="capitalize">{selection}</td>
                <td>{frame.normalized_distance?.toFixed(3) ?? "—"}</td>
                <td>
                  <StatusBadge status={frame.status} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
