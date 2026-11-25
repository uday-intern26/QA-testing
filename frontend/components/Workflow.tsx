"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ApplicationRecord, CatalogCategory, DashboardData, FrameRow, QaReport, RunStatus, TestRecord } from "@/lib/api";
import { ApplicationConfig } from "./ApplicationConfig";
import { BackButton } from "./BackButton";
import { StatusBadge } from "./StatusBadge";
import { Card, Field, inputClass } from "./Shell";
import { CapturedFrameGallery } from "./CapturedFrameGallery";
import { TestProgress } from "./TestProgress";

const JEWELRY_TYPES = [
  { value: "earring", category: "Earrings", label: "Earring" },
  { value: "necklace", category: "Necklaces", label: "Necklace" },
  { value: "bracelet", category: "Bracelets", label: "Bracelet" },
  { value: "ring", category: "Rings", label: "Ring" },
  { value: "bangle", category: "Bangles", label: "Bangle" },
] as const;

export function Workflow() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [application, setApplication] = useState<ApplicationRecord | null>(null);
  // Always use whatever the tester types in Step 1 — each try-on link has its own login.
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [test, setTest] = useState<TestRecord | null>(null);
  const [savedListVersion, setSavedListVersion] = useState(0);
  const [catalog, setCatalog] = useState<CatalogCategory[]>([]);
  const [jewelryType, setJewelryType] = useState<(typeof JEWELRY_TYPES)[number]["value"]>("earring");
  const [chosen, setChosen] = useState("");
  const [selectedFinger, setSelectedFinger] = useState<"thumb" | "index" | "middle" | "ring" | "little">("ring");
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [report, setReport] = useState<QaReport | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [selectedFrame, setSelectedFrame] = useState<FrameRow | null>(null);
  useEffect(() => {
    api.dashboard().then(setDashboard).catch(() => setDashboard(null));
  }, [report]);

  useEffect(() => {
    if (!running || !test) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.status(test.id);
        setStatus(next);
        if (next.status === "completed" || next.status === "failed") {
          window.clearInterval(timer);
          setRunning(false);
          setSavedListVersion((version) => version + 1);
          if (next.status === "completed") {
            const result = await api.results(test.id);
            setReport(result);
          }
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "Status polling failed");
      }
    }, 800);
    return () => window.clearInterval(timer);
  }, [running, test]);

  const availableTypes = useMemo(
    () =>
      JEWELRY_TYPES.filter((type) =>
        catalog.some((group) => group.category === type.category && group.items.length > 0)
      ),
    [catalog]
  );
  const jewelryIds = useMemo(() => {
    const category = JEWELRY_TYPES.find((type) => type.value === jewelryType)?.category;
    return catalog.find((group) => group.category === category)?.items || [];
  }, [catalog, jewelryType]);

  function selectJewelryType(nextType: (typeof JEWELRY_TYPES)[number]["value"]) {
    setJewelryType(nextType);
    const category = JEWELRY_TYPES.find((type) => type.value === nextType)?.category;
    const items = catalog.find((group) => group.category === category)?.items || [];
    setChosen(items[0] || "");
  }

  async function runTest() {
    if (!application || !chosen) {
      setError("Validate the try-on, then choose the jewelry type and jewelry ID.");
      return;
    }
    if (!username.trim() || !password) {
      setError("Enter the username and password for this try-on link in Step 1 before running.");
      return;
    }
    setError("");
    setReport(null);
    try {
      const earringDefaults = jewelryType === "earring";
      const necklaceDefaults = jewelryType === "necklace";
      const ringDefaults = jewelryType === "ring";
      const braceletDefaults = jewelryType === "bracelet";
      const bangleDefaults = jewelryType === "bangle";
      const created = await api.createTest({
        name: `Placement · ${chosen}`,
        application_id: application.id,
        reference_id: null,
        jewelry_id: chosen,
        jewelry_type: jewelryType,
        ear_side: jewelryType === "earring" ? "both" : "left",
        selected_finger: ringDefaults ? selectedFinger : null,
        capture_fps: 10,
        // Backend expands this to the face-video length so left and right turns are captured.
        capture_duration_seconds: 1,
        min_selected_frames: 5,
        max_selected_frames: 10,
        minimum_confidence: earringDefaults || necklaceDefaults || ringDefaults || braceletDefaults || bangleDefaults ? 0.8 : 0.5,
        pass_threshold: earringDefaults || necklaceDefaults ? 0.02 : ringDefaults || bangleDefaults ? 0.08 : 0.1,
        fail_threshold: earringDefaults || necklaceDefaults ? 0.05 : braceletDefaults ? 0.18 : 0.15,
        minimum_pass_rate: 0.95,
        maximum_consecutive_failures: 2,
      });
      setTest(created);
      setRunning(true);
      await api.runTest(created.id, { username, password });
      setStatus(await api.status(created.id));
    } catch (exc) {
      setRunning(false);
      setError(exc instanceof Error ? exc.message : "Unable to start the test");
    }
  }

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <BackButton label="Back" disabled={!running && !report} />
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">AIJewel QA · Try-On</p>
          <h2 className="mt-1 text-2xl font-semibold">Jewelry try-on placement</h2>
          <p className="mt-2 max-w-3xl text-sm text-zinc-400">
            Enter the try-on link and a face video. The try-on page opens automatically with that video as
            the camera. Then choose a jewelry category (earring, necklace, bracelet, ring, or bangle) and
            jewelry ID. The result is PASS when the piece sits on the body attachment point, and FAIL otherwise.
          </p>
        </div>
      </header>
      {dashboard ? (
        <div className="grid gap-3 md:grid-cols-4">
          <Summary label="Total tests" value={String(dashboard.total_tests)} />
          <Summary label="Passed" value={String(dashboard.passed)} />
          <Summary label="Failed" value={String(dashboard.failed)} />
          <Summary label="Warnings" value={String(dashboard.warnings)} />
        </div>
      ) : null}
      <div className="flex flex-wrap gap-4 text-sm text-zinc-400">
        {dashboard?.latest_test ? (
          <p>
            Latest test: {dashboard.latest_test.test_name}{" "}
            <Link className="underline" href={`/tests/${dashboard.latest_test.test_id}`}>
              {dashboard.latest_test.test_id}
            </Link>
          </p>
        ) : null}
        {dashboard?.latest_failure ? (
          <p>
            Latest failure: {dashboard.latest_failure.test_name}{" "}
            <Link className="underline" href={`/tests/${dashboard.latest_failure.test_id}`}>
              {dashboard.latest_failure.test_id}
            </Link>
          </p>
        ) : null}
        <p>
          Average pass rate:{" "}
          {dashboard?.average_pass_rate == null ? "n/a" : `${(dashboard.average_pass_rate * 100).toFixed(1)}%`}
        </p>
      </div>

      <section className="space-y-3">
        <StepHeading step="1" title="Try-On Application" />
        <ApplicationConfig
          selectedId={application?.id}
          listVersion={savedListVersion}
          username={username}
          password={password}
          onUsernameChange={setUsername}
          onPasswordChange={setPassword}
          onSelect={(item) => {
            setApplication(item);
          }}
          onReady={(item, groups) => {
            setApplication(item);
            setCatalog(groups);
            const firstType =
              JEWELRY_TYPES.find((type) =>
                groups.some((group) => group.category === type.category && group.items.length > 0)
              ) || JEWELRY_TYPES[0];
            setJewelryType(firstType.value);
            setChosen(groups.find((group) => group.category === firstType.category)?.items[0] || "");
            setReport(null);
            setStatus(null);
          }}
        />
      </section>

      {catalog.some((group) => group.items.length) ? (
        <Card title="Choose the jewelry to test" step="2">
          <p className="mb-3 text-sm text-zinc-400">
            Select the jewelry type first. The jewelry ID list is filled from the try-on URL for that type.
          </p>
          <div className={`grid gap-3 ${jewelryType === "ring" ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
            <Field label="Jewelry type">
              <select
                className={inputClass}
                value={jewelryType}
                onChange={(event) => selectJewelryType(event.target.value as typeof jewelryType)}
              >
                {(availableTypes.length ? availableTypes : JEWELRY_TYPES).map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Jewelry ID">
              <select
                className={inputClass}
                value={chosen}
                onChange={(event) => setChosen(event.target.value)}
                disabled={!jewelryIds.length}
              >
                {!jewelryIds.length ? <option value="">No jewelry for this type</option> : null}
                {jewelryIds.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </Field>
            {jewelryType === "ring" ? (
              <Field label="Selected finger">
                <select
                  className={inputClass}
                  value={selectedFinger}
                  onChange={(event) => setSelectedFinger(event.target.value as typeof selectedFinger)}
                >
                  <option value="thumb">Thumb</option>
                  <option value="index">Index</option>
                  <option value="middle">Middle</option>
                  <option value="ring">Ring</option>
                  <option value="little">Little</option>
                </select>
              </Field>
            ) : null}
          </div>
          <button
            type="button"
            onClick={runTest}
            disabled={running || !chosen}
            className="mt-4 rounded bg-zinc-100 px-6 py-3 text-base font-semibold text-zinc-950 disabled:opacity-50"
          >
            {running ? "Testing placement…" : "Test this jewelry"}
          </button>
        {error ? <p className="mt-3 text-sm text-red-400">{error}</p> : null}
        <div className="mt-6">
          <TestProgress status={status} />
        </div>
      </Card>
      ) : null}

      {report ? (
        <Card title="Result" step="3">
          <div className="mb-4">
            <button
              type="button"
              onClick={() => {
                setReport(null);
                setStatus(null);
                setSelectedFrame(null);
                setError("");
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
              aria-label="Back to new test"
              title="Back to new test"
              className="inline-flex items-center gap-2 rounded border border-zinc-700 bg-zinc-950 px-2.5 py-1.5 text-sm text-zinc-200 hover:border-zinc-500 hover:bg-zinc-900"
            >
              <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
                className="h-4 w-4 shrink-0"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M15 18l-6-6 6-6" />
                <path d="M9 12h12" />
              </svg>
              <span>Back</span>
            </button>
          </div>
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-6 text-center">
            <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">Overall result</p>
            <div className="mt-3 flex justify-center">
              <StatusBadge status={report.overall_status} />
            </div>
            <p className="mt-4 text-sm text-zinc-300">
              {report.statistics?.frames_captured ?? 0} frames captured
              {report.statistics?.best_frame_number != null
                ? ` · best match is frame ${String(report.statistics.best_frame_number).padStart(3, "0")}`
                : ""}
            </p>
            {typeof report.statistics?.jewelry_lay_seconds === "number" ? (
              <p className="mt-4 text-sm text-zinc-300">
                Jewelry laid on the video in {report.statistics.jewelry_lay_seconds.toFixed(1)} seconds
              </p>
            ) : null}
          </div>
          <div className="mt-6">
            <CapturedFrameGallery
              report={report}
              active={selectedFrame}
              onSelect={setSelectedFrame}
            />
          </div>
          {selectedFrame ? (
            <FrameDetail frame={selectedFrame} onClose={() => setSelectedFrame(null)} />
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

function frameReason(frame: FrameRow, explain = true) {
  const raw =
    frame.failure_reason || frame.landmark_validation?.failure_reason || frame.reason || "";
  if (!raw) return frame.status === "PASS" ? "This frame passed." : "No reason recorded.";
  if (!explain) return raw;
  return REASON_TEXT[raw] || raw;
}

const REASON_TEXT: Record<string, string> = {
  TRACKING_LOST: "Tracking was lost, so the jewelry could not be checked on this frame.",
  REQUIRED_LANDMARK_NOT_DETECTED: "The body point needed for this jewelry was not detected.",
  LANDMARK_NOT_DETECTED: "The body point needed for this jewelry was not detected.",
  LOW_LANDMARK_CONFIDENCE: "The body point was detected, but the confidence was too low.",
  ATTACHMENT_POSITION_OUT_OF_TOLERANCE: "The jewelry is not on the attachment point.",
  ATTACHMENT_POSITION_MISMATCH: "The jewelry is not on the attachment point.",
  NORMALIZED_DISTANCE_EXCEEDED: "The jewelry is too far from the attachment point.",
  ROTATION_OUT_OF_TOLERANCE: "The jewelry rotation is outside the allowed range.",
  SCALE_OUT_OF_RANGE: "The jewelry size does not match the attachment point.",
  TEMPORAL_DRIFT: "The jewelry moved away from the attachment point across frames.",
  INVALID_FRAME: "This frame could not be tested.",
  EARRING_MODEL_NOT_LOADED: "The earring model was not loaded on this frame.",
  ATTACHMENT_ANCHOR_MISSING: "The jewelry attachment point was missing on this frame.",
  DUPLICATE_FRAME_SKIPPED: "This frame was skipped because it repeats an earlier frame.",
};

function FrameDetail({ frame, onClose }: { frame: FrameRow; onClose: () => void }) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const reason = frameReason(frame);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Frame ${frame.frame_number}`}
        className="max-h-[90vh] w-full max-w-4xl overflow-auto rounded-lg border border-zinc-700 bg-zinc-950 p-4"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-200">
            Frame {String(frame.frame_number).padStart(3, "0")}
            {frame.side ? ` · ${frame.side}` : ""}
          </p>
          <div className="flex items-center gap-3">
            <StatusBadge status={frame.status} />
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-zinc-700 px-2 py-1 text-sm text-zinc-300"
            >
              Close
            </button>
          </div>
        </div>
        <img
          src={api.asset(frame.annotated_image_url || frame.image_url)}
          alt={`Frame ${frame.frame_number} with placement overlay`}
          className="max-h-[68vh] w-full rounded object-contain"
        />
        <p className="mt-4 text-sm text-zinc-300">
          {frame.timestamp_ms != null ? `${(frame.timestamp_ms / 1000).toFixed(1)}s · ` : ""}
          {frame.placement_accuracy != null ? `${frame.placement_accuracy.toFixed(1)}% tracing match · ` : ""}
          {frame.normalized_distance != null ? `distance ${frame.normalized_distance.toFixed(3)} · ` : ""}
          {reason}
        </p>
      </div>
    </div>
  );
}

function StepHeading({ step, title }: { step: string; title: string }) {
  return (
    <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">
      Step {step} · {title}
    </p>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900 px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl text-zinc-100">{value}</p>
    </div>
  );
}
