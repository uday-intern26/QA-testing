"use client";

import { useEffect, useMemo, useState } from "react";
import { api, DebugProfile } from "@/lib/api";
import { Field, inputClass } from "./Shell";

const DISPLAY_TOGGLES: { key: string; label: string }[] = [
  { key: "show_face_mesh", label: "Show face mesh" },
  { key: "show_landmark_numbers", label: "Show landmark numbers" },
  { key: "highlight_selected_landmark", label: "Highlight selected landmark" },
  { key: "show_expected_point", label: "Show expected attachment point" },
  { key: "show_actual_point", label: "Show actual attachment point" },
  { key: "show_deviation", label: "Show position deviation" },
  { key: "show_confidence", label: "Show confidence score" },
  { key: "show_frame_validation", label: "Show frame-by-frame validation" },
];

const TOLERANCE_FIELDS: { key: string; label: string; step: string }[] = [
  { key: "position_tolerance_px", label: "Position tolerance (px)", step: "0.5" },
  { key: "position_tolerance_normalized", label: "Position tolerance (normalized)", step: "0.01" },
  { key: "rotation_tolerance_deg", label: "Rotation tolerance (degrees)", step: "1" },
  { key: "minimum_valid_frame_percentage", label: "Minimum valid frame %", step: "1" },
  { key: "scale_min_ratio", label: "Minimum scale ratio", step: "0.05" },
  { key: "scale_max_ratio", label: "Maximum scale ratio", step: "0.05" },
  { key: "minimum_landmark_confidence", label: "Minimum landmark confidence", step: "0.05" },
  { key: "max_consecutive_tracking_failures", label: "Max consecutive tracking failures", step: "1" },
];

export type DebugOptions = Record<string, number | boolean>;

/**
 * Debug configuration for one jewellery category. Defaults come from the
 * backend profile for that category, so each type keeps its own tolerances.
 */
export function DebugModePanel({
  jewelryType,
  enabled,
  options,
  onToggle,
  onChange,
}: {
  jewelryType: string;
  enabled: boolean;
  options: DebugOptions;
  onToggle: (next: boolean) => void;
  onChange: (next: DebugOptions) => void;
}) {
  const [profiles, setProfiles] = useState<Record<string, DebugProfile>>({});

  useEffect(() => {
    let cancelled = false;
    api
      .settings()
      .then((data) => {
        const available = (data as { debug_profiles?: Record<string, DebugProfile> }).debug_profiles;
        if (!cancelled && available) setProfiles(available);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const profile = useMemo(() => profiles[jewelryType] || profiles.earring, [profiles, jewelryType]);

  function toleranceValue(key: string): number | string {
    if (key in options) return options[key] as number;
    const defaults = profile?.tolerances as unknown as Record<string, number> | undefined;
    return defaults?.[key] ?? "";
  }

  function displayValue(key: string): boolean {
    if (key in options) return Boolean(options[key]);
    const defaults = profile?.display as unknown as Record<string, boolean> | undefined;
    return defaults?.[key] ?? true;
  }

  return (
    <div className="md:col-span-2 rounded border border-[var(--border)] bg-[var(--card)] px-3 py-3">
      <label className="flex items-center gap-2 text-sm text-[var(--text)]">
        <input type="checkbox" checked={enabled} onChange={(event) => onToggle(event.target.checked)} />
        <span className="font-medium">Visual Debug Mode</span>
        <span className="text-[var(--muted)]">
          — renders the landmark mesh, expected vs actual attachment points, and makes the landmark
          validation authoritative for the verdict.
        </span>
      </label>

      {!enabled ? (
        <p className="mt-2 text-xs text-[var(--muted)]">
          Off: no debug frames are rendered and the run behaves exactly as before. Landmark
          measurements are still reported, but they do not change the PASS/FAIL verdict.
        </p>
      ) : (
        <div className="mt-3 space-y-4">
          <p className="text-xs text-[var(--muted)]">
            Settings below apply to <span className="text-[var(--text)]">{profile?.label || jewelryType}</span>{" "}
            only (attachment region: {profile?.body_region || "—"}). Leave a field untouched to use the
            category default.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {DISPLAY_TOGGLES.map((toggle) => (
              <label key={toggle.key} className="flex items-center gap-2 text-sm text-[var(--muted)]">
                <input
                  type="checkbox"
                  checked={displayValue(toggle.key)}
                  onChange={(event) => onChange({ ...options, [toggle.key]: event.target.checked })}
                />
                {toggle.label}
              </label>
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {TOLERANCE_FIELDS.map((item) => (
              <Field key={item.key} label={item.label}>
                <input
                  className={inputClass}
                  type="number"
                  step={item.step}
                  value={toleranceValue(item.key)}
                  onChange={(event) =>
                    onChange({ ...options, [item.key]: Number(event.target.value) })
                  }
                />
              </Field>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
