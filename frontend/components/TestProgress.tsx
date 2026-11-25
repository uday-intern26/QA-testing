import { useRef } from "react";
import { api, RunStatus } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

const LABELS: Record<string, string> = {
  application: "Application",
  authentication: "Authentication",
  capture: "Capture",
  frame_selection: "Layer 1 — Frame Selection",
  earlobe_detection: "Layer 2 — Body Anchor Detection",
  earring_detection: "Layer 2 — Jewelry Anchor Detection",
  placement_validation: "Layer 3 — Placement Validation",
  report: "Report",
};

export function TestProgress({ status }: { status: RunStatus | null }) {
  const previewTick = useRef(0);
  if (!status) return null;
  previewTick.current += 1;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-300">{status.stage_message}</p>
        <StatusBadge status={status.overall_status || status.status} />
      </div>
      <div className="h-2 overflow-hidden rounded bg-zinc-800">
        <div className="h-full bg-zinc-200" style={{ width: `${Math.max(0, Math.min(100, status.progress))}%` }} />
      </div>
      <ul className="space-y-2">
        {status.steps.map((step) => (
          <li key={step.name} className="flex items-center justify-between gap-3 text-sm">
            <span>
              <span className="text-zinc-200">{LABELS[step.name] || step.name}</span>
              {step.detail ? <span className="ml-2 text-zinc-500">{step.detail}</span> : null}
            </span>
            <StatusBadge status={step.status} />
          </li>
        ))}
      </ul>
      {status.preview_image_url ? (
        <img
          src={`${api.asset(status.preview_image_url)}?t=${previewTick.current}`}
          alt="Latest captured try-on frame"
          className="max-h-64 w-full rounded border border-zinc-800 object-contain"
        />
      ) : null}
      {status.reason ? <p className="text-sm text-zinc-300">{status.reason}</p> : null}
      {status.recommended_action ? <p className="text-sm text-zinc-500">Recommended action: {status.recommended_action}</p> : null}
    </div>
  );
}
