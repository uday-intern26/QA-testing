import { QaReport } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";
import { TestLayers, layerStatus } from "./TestLayers";

export function ResultSummary({ report }: { report: QaReport }) {
  const stats = report.statistics;
  const frameLayer = layerStatus(report.layers.frame_selection);
  const anchorLayer = layerStatus(report.layers.anchor_detection);
  const placementLayer = layerStatus(report.layers.placement_validation);
  const reference = report.reference_comparison;
  const actual = reference?.sides?.[0];
  const temporalEntries = Object.entries(report.temporal || {});
  return (
    <div className="space-y-6">
      <div className="grid gap-2 text-sm text-zinc-400 md:grid-cols-2">
        <p>Application: {report.application?.url || report.application?.name || "n/a"}</p>
        <p>
          Jewellery: {report.jewelry_id || "unspecified"} · {report.ear_side?.toUpperCase() || "n/a"}
        </p>
        <p>Run: {report.test_run_id}</p>
      </div>
      <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-6 text-center">
        <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">Overall result</p>
        <div className="mt-3 flex justify-center">
          <StatusBadge status={report.overall_status} />
        </div>
        <div className="mt-6 grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
          <Metric label="Pass rate" value={stats ? `${(stats.pass_rate * 100).toFixed(1)}%` : "n/a"} />
          <Metric label="Frames tested" value={String(stats?.frames_selected ?? 0)} />
          <Metric label="Passed" value={String(stats?.frames_passed ?? 0)} />
          <Metric label="Failed" value={String(stats?.frames_failed ?? 0)} />
        </div>
        {report.reason ? <p className="mt-4 text-sm text-zinc-300">{report.reason}</p> : null}
        {report.recommended_action ? (
          <p className="mt-2 text-sm text-zinc-500">Recommended action: {report.recommended_action}</p>
        ) : null}
      </div>
      <div>
        <p className="mb-3 text-xs uppercase tracking-[0.2em] text-zinc-500">Three-layer validation</p>
        <TestLayers
          layers={[
            {
              title: "Layer 1 — Frame Selection",
              subtitle: "Select representative frames",
              status: frameLayer.status,
              detail: frameLayer.detail,
            },
            {
              title: "Layer 2 — Earlobe + Earring Anchor Detection",
              subtitle: "Locate both points",
              status: anchorLayer.status,
              detail: anchorLayer.detail,
            },
            {
              title: "Layer 3 — Placement Validation",
              subtitle: "PASS / WARNING / FAIL",
              status: placementLayer.status,
              detail: placementLayer.detail,
            },
          ]}
        />
      </div>
      {reference && reference.status !== "NOT_RUN" ? (
        <div className="rounded-lg border border-zinc-800 p-4 text-sm">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-zinc-200">Reference comparison</h3>
            <StatusBadge status={reference.status} />
          </div>
          <p className="mt-2 text-zinc-400">Reference distance: {actual?.magnitude_reference?.toFixed(3) ?? "n/a"}</p>
          <p className="text-zinc-400">Actual distance: {actual?.magnitude_actual?.toFixed(3) ?? "n/a"}</p>
          <p className="text-zinc-400">Difference: {actual?.distance_error?.toFixed(3) ?? "n/a"}</p>
          {actual?.angle_error != null ? <p className="text-zinc-400">Angle error: {actual.angle_error.toFixed(1)}°</p> : null}
          <p className="mt-2 text-zinc-500">{reference.reason}</p>
        </div>
      ) : null}
      {report.jewelry_type === "bangle" && report.bangle_lay ? (
        <div className="rounded-lg border border-zinc-800 p-4 text-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="font-medium text-zinc-200">
              Bangle lay result
              {report.bangle_lay.wrist_side ? ` · ${report.bangle_lay.wrist_side}` : ""}
              {report.bangle_lay.bangle_count && report.bangle_lay.bangle_count > 1
                ? ` · ${report.bangle_lay.bangle_count} bangles`
                : ""}
            </h3>
            <StatusBadge status={report.bangle_lay.final_result} />
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {(
              [
                ["Wrist Detection", "wrist_detection"],
                ["Wrist Landmark Detection", "wrist_landmark_detection"],
                ["Bangle Placement", "bangle_placement"],
                ["Wrist Alignment", "wrist_alignment"],
                ["Circular/Oval Alignment", "circular_oval_alignment"],
                ["Center Alignment", "bangle_center_alignment"],
                ["Wrist Coverage", "wrist_coverage"],
                ["Hand Clearance", "hand_clearance"],
                ["Forearm Clearance", "forearm_clearance"],
                ["Multiple Bangle Spacing", "multiple_bangle_spacing"],
              ] as const
            ).map(([label, key]) => (
              <div key={key} className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
                <span className="text-zinc-400">{label}</span>
                <StatusBadge status={report.bangle_lay?.checks?.[key] || "FAIL"} />
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <Metric
              label="Overall bangle lay accuracy"
              value={`${report.bangle_lay.overall_bangle_lay_accuracy_pct.toFixed(1)}%`}
            />
            <Metric label="Final result" value={report.bangle_lay.final_result} />
          </div>
          {report.bangle_lay.ground_truth_accuracy_pct != null ? (
            <p className="mt-2 text-zinc-400">
              Ground-truth accuracy (vs manual reviews): {report.bangle_lay.ground_truth_accuracy_pct.toFixed(1)}%
            </p>
          ) : null}
          {report.bangle_lay.reason ? <p className="mt-2 text-zinc-400">{report.bangle_lay.reason}</p> : null}
          {report.bangle_lay.note ? <p className="mt-1 text-xs text-zinc-500">{report.bangle_lay.note}</p> : null}
        </div>
      ) : null}
      {report.jewelry_type === "bracelet" && report.bracelet_lay ? (
        <div className="rounded-lg border border-zinc-800 p-4 text-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="font-medium text-zinc-200">
              Bracelet lay result
              {report.bracelet_lay.wrist_side ? ` · ${report.bracelet_lay.wrist_side}` : ""}
              {report.bracelet_lay.bracelet_style ? ` · ${report.bracelet_lay.bracelet_style}` : ""}
            </h3>
            <StatusBadge status={report.bracelet_lay.final_result} />
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {(
              [
                ["Wrist Detection", "wrist_detection"],
                ["Wrist Landmark Detection", "wrist_landmark_detection"],
                ["Bracelet Placement", "bracelet_placement"],
                ["Wrist Alignment", "wrist_alignment"],
                ["Center Alignment", "bracelet_center_alignment"],
                ["Wrist Coverage", "wrist_coverage"],
                ["Hand Clearance", "hand_clearance"],
                ["Forearm Clearance", "forearm_clearance"],
              ] as const
            ).map(([label, key]) => (
              <div key={key} className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
                <span className="text-zinc-400">{label}</span>
                <StatusBadge status={report.bracelet_lay?.checks?.[key] || "FAIL"} />
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <Metric
              label="Overall bracelet lay accuracy"
              value={`${report.bracelet_lay.overall_bracelet_lay_accuracy_pct.toFixed(1)}%`}
            />
            <Metric label="Final result" value={report.bracelet_lay.final_result} />
          </div>
          {report.bracelet_lay.ground_truth_accuracy_pct != null ? (
            <p className="mt-2 text-zinc-400">
              Ground-truth accuracy (vs manual reviews): {report.bracelet_lay.ground_truth_accuracy_pct.toFixed(1)}%
            </p>
          ) : null}
          {report.bracelet_lay.reason ? <p className="mt-2 text-zinc-400">{report.bracelet_lay.reason}</p> : null}
          {report.bracelet_lay.note ? <p className="mt-1 text-xs text-zinc-500">{report.bracelet_lay.note}</p> : null}
        </div>
      ) : null}
      {report.jewelry_type === "ring" && report.ring_lay ? (
        <div className="rounded-lg border border-zinc-800 p-4 text-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="font-medium text-zinc-200">
              Ring lay result{report.ring_lay.selected_finger ? ` · ${report.ring_lay.selected_finger}` : ""}
            </h3>
            <StatusBadge status={report.ring_lay.final_result} />
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {(
              [
                ["Hand Detection", "hand_detection"],
                ["Selected Finger Detection", "selected_finger_detection"],
                ["Ring Placement", "ring_placement"],
                ["Finger Alignment", "finger_alignment"],
                ["Ring Center Alignment", "ring_center_alignment"],
                ["Knuckle Clearance", "knuckle_clearance"],
                ["Ring Orientation", "ring_orientation"],
              ] as const
            ).map(([label, key]) => (
              <div key={key} className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
                <span className="text-zinc-400">{label}</span>
                <StatusBadge status={report.ring_lay?.checks?.[key] || "FAIL"} />
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <Metric
              label="Overall ring lay accuracy"
              value={`${report.ring_lay.overall_ring_lay_accuracy_pct.toFixed(1)}%`}
            />
            <Metric label="Final result" value={report.ring_lay.final_result} />
          </div>
          {report.ring_lay.ground_truth_accuracy_pct != null ? (
            <p className="mt-2 text-zinc-400">
              Ground-truth accuracy (vs manual reviews): {report.ring_lay.ground_truth_accuracy_pct.toFixed(1)}%
            </p>
          ) : null}
          {report.ring_lay.reason ? <p className="mt-2 text-zinc-400">{report.ring_lay.reason}</p> : null}
          {report.ring_lay.note ? <p className="mt-1 text-xs text-zinc-500">{report.ring_lay.note}</p> : null}
        </div>
      ) : null}
      {report.jewelry_type === "earring" && report.earring_lay ? (
        <div className="rounded-lg border border-zinc-800 p-4 text-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="font-medium text-zinc-200">Earring lay result</h3>
            <StatusBadge status={report.earring_lay.final_result} />
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {(
              [
                ["Left Ear Detection", "left_ear_detection"],
                ["Right Ear Detection", "right_ear_detection"],
                ["Left Earring Placement", "left_earring_placement"],
                ["Right Earring Placement", "right_earring_placement"],
                ["Earlobe Alignment", "earlobe_alignment"],
                ["Symmetry", "symmetry"],
                ["Hanging Alignment", "hanging_alignment"],
              ] as const
            ).map(([label, key]) => (
              <div key={key} className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
                <span className="text-zinc-400">{label}</span>
                <StatusBadge status={report.earring_lay?.checks?.[key] || "FAIL"} />
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <Metric
              label="Overall earring lay accuracy"
              value={`${report.earring_lay.overall_earring_lay_accuracy_pct.toFixed(1)}%`}
            />
            <Metric label="Final result" value={report.earring_lay.final_result} />
          </div>
          {report.earring_lay.ground_truth_accuracy_pct != null ? (
            <p className="mt-2 text-zinc-400">
              Ground-truth accuracy (vs manual reviews): {report.earring_lay.ground_truth_accuracy_pct.toFixed(1)}%
            </p>
          ) : null}
          {report.earring_lay.reason ? <p className="mt-2 text-zinc-400">{report.earring_lay.reason}</p> : null}
          {report.earring_lay.note ? <p className="mt-1 text-xs text-zinc-500">{report.earring_lay.note}</p> : null}
        </div>
      ) : null}
      {report.jewelry_type === "necklace" && report.necklace_lay ? (
        <div className="rounded-lg border border-zinc-800 p-4 text-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="font-medium text-zinc-200">Necklace lay result</h3>
            <StatusBadge status={report.necklace_lay.final_result} />
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {(
              [
                ["Neck Detection", "neck_detection"],
                ["Necklace Placement", "necklace_placement"],
                ["Neckline Alignment", "neckline_alignment"],
                ["Center Alignment", "center_alignment"],
                ["Pendant Position", "pendant_position"],
                ["Shoulder Clearance", "shoulder_clearance"],
              ] as const
            ).map(([label, key]) => (
              <div key={key} className="flex items-center justify-between rounded border border-zinc-800 px-3 py-2">
                <span className="text-zinc-400">{label}</span>
                <StatusBadge status={report.necklace_lay?.checks?.[key] || "FAIL"} />
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <Metric
              label="Overall necklace lay accuracy"
              value={`${report.necklace_lay.overall_necklace_lay_accuracy_pct.toFixed(1)}%`}
            />
            <Metric label="Final result" value={report.necklace_lay.final_result} />
          </div>
          {report.necklace_lay.ground_truth_accuracy_pct != null ? (
            <p className="mt-2 text-zinc-400">
              Ground-truth accuracy (vs manual reviews): {report.necklace_lay.ground_truth_accuracy_pct.toFixed(1)}%
            </p>
          ) : null}
          {report.necklace_lay.reason ? <p className="mt-2 text-zinc-400">{report.necklace_lay.reason}</p> : null}
          {report.necklace_lay.note ? <p className="mt-1 text-xs text-zinc-500">{report.necklace_lay.note}</p> : null}
        </div>
      ) : null}
      {temporalEntries.length ? (
        <div className="rounded-lg border border-zinc-800 p-4 text-sm">
          <h3 className="mb-3 font-medium text-zinc-200">Temporal stability</h3>
          {temporalEntries.map(([side, summary]) => (
            <div key={side} className="mb-3 last:mb-0">
              <div className="flex items-center justify-between">
                <p className="capitalize text-zinc-300">{side} {report.jewelry_type === "necklace" ? "neck" : "ear"}</p>
                <StatusBadge status={summary.status} />
              </div>
              <p className="mt-1 text-zinc-400">
                Pass rate {(summary.pass_rate * 100).toFixed(1)}% · Max consecutive failures {summary.max_consecutive_failures}{" "}
                · Allowed {report.thresholds.maximum_consecutive_failures}
              </p>
              <p className="text-zinc-500">{summary.reason}</p>
            </div>
          ))}
        </div>
      ) : null}
      <p className="text-xs text-zinc-500">
        Captured {stats?.frames_captured ?? 0} · Analyzed {stats?.frames_analyzed ?? 0} · Selected {stats?.frames_selected ?? 0} ·
        Warnings {stats?.frames_warning ?? 0} · Max consecutive failures {stats?.max_consecutive_failures ?? 0}
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-xl text-zinc-100">{value}</p>
    </div>
  );
}
