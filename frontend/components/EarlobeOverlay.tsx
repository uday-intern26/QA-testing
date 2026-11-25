"use client";

import { useEffect, useState } from "react";
import { api, FrameLandmarks } from "@/lib/api";

interface Point {
  x: number;
  y: number;
}

interface Props {
  earlobe: Point | null;
  earring: Point | null;
  earWidth: number;
  zoneYScale?: number;
  passThreshold: number;
  failThreshold: number;
  normalizedDistance?: number | null;
  showLandmarks: boolean;
  showEarring: boolean;
  showZone: boolean;
  showMeasurement: boolean;
  /** Runtime MediaPipe landmarks for this frame. Fetched only when needed. */
  landmarksUrl?: string | null;
  side?: string;
}

/** Fetches the stored runtime landmarks once the user asks to see them. */
function useFrameLandmarks(url: string | null | undefined, enabled: boolean) {
  const [data, setData] = useState<FrameLandmarks | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!enabled || !url) return;
    let cancelled = false;
    setError("");
    api
      .frameLandmarks(url)
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((exc: Error) => {
        if (!cancelled) {
          setData(null);
          setError(exc.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [url, enabled]);

  return { data, error };
}

export function EarlobeOverlay({
  earlobe,
  earring,
  earWidth,
  zoneYScale = 1,
  passThreshold,
  failThreshold,
  normalizedDistance,
  showLandmarks,
  showEarring,
  showZone,
  showMeasurement,
  landmarksUrl,
  side = "left",
}: Props) {
  const { data: landmarks, error: landmarkError } = useFrameLandmarks(landmarksUrl, showLandmarks);

  if (!earlobe && !landmarks) return null;

  const width = Math.max(earWidth, 0.01);
  const outerW = failThreshold * width * 2 * 100;
  const outerH = failThreshold * width * zoneYScale * 2 * 100;
  const innerW = passThreshold * width * 2 * 100;
  const innerH = passThreshold * width * zoneYScale * 2 * 100;

  const meshPoints = landmarks?.uses_hand_landmarks ? landmarks?.hand : landmarks?.face;
  const contour = landmarks?.contours?.[side] || [];
  const otherSide = side === "left" ? "right" : "left";
  const otherContour = landmarks?.contours?.[otherSide] || [];
  const selectedIndex = landmarks?.selected_landmarks?.[side];

  return (
    <div className="pointer-events-none absolute inset-0">
      {showZone && earlobe ? (
        <>
          <div
            className="absolute rounded-full border-2 border-yellow-400/80"
            style={{
              left: `${earlobe.x * 100 - outerW / 2}%`,
              top: `${earlobe.y * 100 - outerH / 2}%`,
              width: `${outerW}%`,
              height: `${outerH}%`,
            }}
            title={`Fail tolerance: ${failThreshold.toFixed(3)} normalized`}
          />
          <div
            className="absolute rounded-full border border-sky-300/80"
            style={{
              left: `${earlobe.x * 100 - innerW / 2}%`,
              top: `${earlobe.y * 100 - innerH / 2}%`,
              width: `${innerW}%`,
              height: `${innerH}%`,
            }}
            title={`Pass tolerance: ${passThreshold.toFixed(3)} normalized`}
          />
        </>
      ) : null}

      {showLandmarks && meshPoints?.length ? (
        <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          {/* Full runtime mesh. Index labels are thinned so they stay readable. */}
          {meshPoints.map((point, index) => (
            <circle key={index} cx={point[0] * 100} cy={point[1] * 100} r={0.15} fill="rgba(148,163,184,0.75)" />
          ))}
          {[contour, otherContour].map((indices, group) =>
            indices.length > 1 ? (
              <polyline
                key={group}
                points={indices
                  .filter((index) => index < meshPoints.length)
                  .map((index) => `${meshPoints[index][0] * 100},${meshPoints[index][1] * 100}`)
                  .join(" ")}
                fill="none"
                stroke={group === 0 ? "#fbbf24" : "#38bdf8"}
                strokeWidth={0.25}
              />
            ) : null
          )}
        </svg>
      ) : null}

      {showLandmarks && meshPoints?.length ? (
        <>
          {/* Thinned mesh indices so the full face stays readable. */}
          {meshPoints.map((point, index) =>
            index % 12 === 0 ? (
              <span
                key={`mesh-idx-${index}`}
                className="absolute -translate-x-1/2 -translate-y-1/2 text-[7px] leading-none text-slate-400/80"
                style={{ left: `${point[0] * 100}%`, top: `${point[1] * 100}%` }}
              >
                {index}
              </span>
            ) : null
          )}
          {/* Ear-contour indices are always labeled — these drive earring placement. */}
          {[...contour, ...otherContour]
            .filter((index) => index < meshPoints.length)
            .map((index) => (
              <span
                key={`idx-${index}`}
                className="absolute -translate-x-1/2 -translate-y-1/2 text-[8px] leading-none text-amber-200"
                style={{ left: `${meshPoints[index][0] * 100}%`, top: `${meshPoints[index][1] * 100}%` }}
              >
                {index}
              </span>
            ))}
          {selectedIndex != null && selectedIndex < meshPoints.length ? (
            <span
              title={`Earlobe landmark #${selectedIndex} used by the placement script`}
              className="absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-amber-300 bg-amber-300/20"
              style={{
                left: `${meshPoints[selectedIndex][0] * 100}%`,
                top: `${meshPoints[selectedIndex][1] * 100}%`,
              }}
            />
          ) : null}
          {selectedIndex != null && selectedIndex < meshPoints.length ? (
            <span
              className="absolute -translate-y-5 text-[9px] font-medium text-amber-200"
              style={{
                left: `${meshPoints[selectedIndex][0] * 100}%`,
                top: `${meshPoints[selectedIndex][1] * 100}%`,
              }}
            >
              #{selectedIndex} earlobe
            </span>
          ) : null}
        </>
      ) : null}

      {showLandmarks && !meshPoints?.length ? (
        <span className="absolute left-2 top-2 rounded bg-black/70 px-2 py-1 text-xs text-amber-300">
          {landmarkError || "No stored landmarks for this frame. Re-run the test to capture them."}
        </span>
      ) : null}

      {showMeasurement && earlobe && earring ? (
        <svg className="absolute inset-0 h-full w-full">
          <line
            x1={`${earlobe.x * 100}%`}
            y1={`${earlobe.y * 100}%`}
            x2={`${earring.x * 100}%`}
            y2={`${earring.y * 100}%`}
            stroke="#f8fafc"
            strokeWidth="2"
          />
          {normalizedDistance != null ? (
            <text
              x={`${((earlobe.x + earring.x) / 2) * 100}%`}
              y={`${((earlobe.y + earring.y) / 2) * 100}%`}
              fill="#f8fafc"
              fontSize="12"
            >
              {normalizedDistance.toFixed(3)}
            </text>
          ) : null}
        </svg>
      ) : null}

      {/* Expected attachment point, always drawn with the jewelry anchor for comparison. */}
      {(showLandmarks || showEarring) && earlobe ? (
        <span
          title="Expected attachment point (from the earlobe landmark)"
          className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-400"
          style={{ left: `${earlobe.x * 100}%`, top: `${earlobe.y * 100}%` }}
        />
      ) : null}

      {showEarring && earlobe && earring ? (
        <svg className="absolute inset-0 h-full w-full">
          <line
            x1={`${earlobe.x * 100}%`}
            y1={`${earlobe.y * 100}%`}
            x2={`${earring.x * 100}%`}
            y2={`${earring.y * 100}%`}
            stroke="#f472b6"
            strokeWidth="1.5"
            strokeDasharray="4 3"
          />
        </svg>
      ) : null}

      {showEarring && earring ? (
        <span
          title="Actual jewelry attachment anchor"
          className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-sm bg-red-500"
          style={{ left: `${earring.x * 100}%`, top: `${earring.y * 100}%` }}
        />
      ) : null}

      {showEarring && !earring ? (
        <span className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-1 text-xs text-red-300">
          No jewelry anchor for this frame
        </span>
      ) : null}
    </div>
  );
}
