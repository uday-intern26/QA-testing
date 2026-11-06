"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ApplicationRecord, CatalogCategory, DashboardData, FrameRow, QaReport, RunStatus, TestRecord } from "@/lib/api";
import { ApplicationConfig } from "./ApplicationConfig";
import { FrameViewer } from "./FrameViewer";
import { PlacementResult } from "./PlacementResult";
import { ResultSummary } from "./ResultSummary";
import { Card, Field, inputClass } from "./Shell";
import { TestLayers, layerStatus } from "./TestLayers";
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
  const [test, setTest] = useState<TestRecord | null>(null);
  const [savedListVersion, setSavedListVersion] = useState(0);
  const [catalog, setCatalog] = useState<CatalogCategory[]>([]);
  const [jewelryType, setJewelryType] = useState<(typeof JEWELRY_TYPES)[number]["value"]>("earring");
  const [chosen, setChosen] = useState("");
  const [earSide, setEarSide] = useState<"left" | "right" | "both">("left");
  const [selectedFinger, setSelectedFinger] = useState<"thumb" | "index" | "middle" | "ring" | "little">("ring");
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [report, setReport] = useState<QaReport | null>(null);
  const [active, setActive] = useState<FrameRow | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [previewTick, setPreviewTick] = useState(0);
  const [frameFilter, setFrameFilter] = useState<"all" | "FAIL" | "WARNING" | "PASS">("all");
  const [reviewReason, setReviewReason] = useState("False positive due to earring occlusion");

  useEffect(() => {
    api.dashboard().then(setDashboard).catch(() => setDashboard(null));
  }, [report]);

  useEffect(() => {
    if (!running || !test) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.status(test.id);
        setStatus(next);
        setPreviewTick(Date.now());
        if (next.status === "completed" || next.status === "failed") {
          window.clearInterval(timer);
          setRunning(false);
          setSavedListVersion((version) => version + 1);
          if (next.status === "completed") {
            const result = await api.results(test.id);
            setReport(result);
            setActive(result.frames.find((frame) => frame.status === "FAIL") || result.frames[0] || null);
          }
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "Status polling failed");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [running, test]);

  const layers = useMemo(() => layersFrom(status, report), [status, report]);
  const visibleFrames = useMemo(() => {
    if (!report) return [];
    if (frameFilter === "all") return report.frames;
    return report.frames.filter((frame) => frame.status === frameFilter);
  }, [report, frameFilter]);
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
        ear_side: jewelryType === "earring" || jewelryType === "bracelet" || jewelryType === "bangle" || jewelryType === "ring" ? earSide : "left",
        selected_finger: ringDefaults ? selectedFinger : null,
        capture_fps: earringDefaults || necklaceDefaults || ringDefaults || braceletDefaults || bangleDefaults ? 10 : 5,
        capture_duration_seconds: 6,
        minimum_confidence: earringDefaults || necklaceDefaults || ringDefaults || braceletDefaults || bangleDefaults ? 0.8 : 0.5,
        pass_threshold: earringDefaults || ringDefaults || bangleDefaults ? 0.08 : 0.1,
        fail_threshold: braceletDefaults ? 0.18 : 0.15,
        minimum_pass_rate: 0.95,
        maximum_consecutive_failures: 2,
      });
      setTest(created);
      setRunning(true);
      await api.runTest(created.id, {});
      setStatus(await api.status(created.id));
    } catch (exc) {
      setRunning(false);
      setError(exc instanceof Error ? exc.message : "Unable to start the test");
    }
  }

  async function review() {
    if (!test || !active) return;
    await api.reviewFrame(test.id, active.frame_id, {
      manual_result: "PASS",
      reviewer: "tester",
      reason: reviewReason,
      side: active.side,
    });
    const result = await api.results(test.id);
    setReport(result);
    setActive(result.frames.find((frame) => frame.frame_id === active.frame_id && frame.side === active.side) || null);
  }

  return (
    <div className="space-y-8">
      <header>
        <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">AIJewel QA · Try-On</p>
        <h2 className="mt-1 text-2xl font-semibold">Earring earlobe alignment</h2>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Enter the try-on link and a face video. The try-on page opens automatically with that video as
          the camera. Then choose jewelry type and jewelry ID. The result is PASS when the piece sits on
          the body attachment point, and FAIL otherwise.
        </p>
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

      <Card title="AIJewel Earring Placement Test">
        <TestLayers layers={layers} />
      </Card>

      <section className="space-y-3">
        <StepHeading step="1" title="Try-On Application" />
        <ApplicationConfig
          selectedId={application?.id}
          listVersion={savedListVersion}
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
          <div className="grid gap-3 md:grid-cols-3">
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
            {jewelryType === "earring" || jewelryType === "bracelet" || jewelryType === "bangle" || jewelryType === "ring" ? (
              <Field label={jewelryType === "earring" ? "Ear visible in the video" : "Side visible in the video"}>
                <select className={inputClass} value={earSide} onChange={(event) => setEarSide(event.target.value as typeof earSide)}>
                  <option value="left">Left</option>
                  <option value="right">Right</option>
                  {jewelryType === "earring" ? <option value="both">Both</option> : null}
                </select>
              </Field>
            ) : (
              <Field label="Attachment check">
                <input className={inputClass} value="Neck / chest placement" readOnly />
              </Field>
            )}
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
        {running && status?.preview_image_url ? (
          <div className="mt-6">
            <p className="mb-2 text-sm text-zinc-300">Selected jewelry on the live video. Pass or fail comes after this.</p>
            <img
              src={`${api.asset(status.preview_image_url)}?t=${previewTick}`}
              alt="Live jewelry overlay"
              className="max-h-[420px] w-full rounded border border-zinc-800 object-contain"
            />
          </div>
        ) : null}
        <div className="mt-6">
          <TestProgress status={status} />
        </div>
      </Card>
      ) : null}

      {report ? (
        <Card title="Result" step="3">
          <PlacementVerdict report={report} />
          <div className="mt-6">
            <ResultSummary report={report} />
          </div>
          <div className="mt-6">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">Frame results</h3>
              <div className="flex gap-2">
                {(["all", "FAIL", "WARNING", "PASS"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setFrameFilter(value)}
                    className={`rounded border px-2 py-1 text-xs ${
                      frameFilter === value ? "border-zinc-300 text-zinc-100" : "border-zinc-700 text-zinc-400"
                    }`}
                  >
                    {value === "all" ? "All frames" : value === "FAIL" ? "Failed frames" : value}
                  </button>
                ))}
              </div>
            </div>
            <div className="mb-4 flex gap-2 overflow-x-auto">
              {visibleFrames.map((frame) => (
                <button
                  key={`${frame.frame_id}-${frame.side}`}
                  type="button"
                  onClick={() => setActive(frame)}
                  className="shrink-0"
                >
                  <img src={api.asset(frame.image_url)} alt="" className="h-16 w-24 rounded object-cover" />
                  <span className="mt-1 block text-xs text-zinc-500">
                    Frame {String(frame.frame_number).padStart(3, "0")}
                  </span>
                </button>
              ))}
            </div>
            <PlacementResult
              frames={visibleFrames}
              activeId={active?.frame_id}
              activeSide={active?.side}
              onSelect={setActive}
            />
            <div className="mt-6">
              <FrameViewer
                frame={active}
                passThreshold={report.thresholds.pass_threshold}
                failThreshold={report.thresholds.fail_threshold}
                zoneYScale={report.thresholds.zone_y_scale || 1}
              />
            </div>
            {active ? (
              <div className="mt-4 flex flex-wrap items-end gap-3">
                <Field label="Review reason">
                  <input className={inputClass} value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} />
                </Field>
                <button type="button" onClick={review} className="rounded border border-zinc-600 px-3 py-2 text-sm">
                  Review Frame
                </button>
                <a className="text-sm underline" href={api.reportUrl(report.test_id)}>
                  Download report
                </a>
                <Link className="text-sm underline" href={`/tests/${report.test_id}`}>
                  Open test detail
                </Link>
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function PlacementVerdict({ report }: { report: QaReport }) {
  const passed = report.overall_status === "PASS";
  return (
    <div className={`rounded-lg border p-6 text-center ${passed ? "border-emerald-500/40 bg-emerald-500/10" : "border-red-500/40 bg-red-500/10"}`}>
      <p className="text-xs uppercase tracking-[0.2em] text-zinc-400">{report.jewelry_id || "Jewelry"}</p>
      <p className={`mt-2 text-4xl font-semibold ${passed ? "text-emerald-300" : "text-red-300"}`}>
        {passed ? "PASS" : "FAIL"}
      </p>
      <p className="mt-3 text-sm text-zinc-300">
        {passed
          ? "The jewelry sits on the attachment point in the video."
          : report.reason || "The jewelry does not sit on the attachment point."}
      </p>
    </div>
  );
}

function layersFrom(status: RunStatus | null, report: QaReport | null) {
  if (report) {
    const frame = layerStatus(report.layers.frame_selection);
    const anchor = layerStatus(report.layers.anchor_detection);
    const placement = layerStatus(report.layers.placement_validation);
    return [
      { title: "LAYER 1", subtitle: "FRAME SELECTION", status: frame.status, detail: frame.detail || "Select representative frames" },
      { title: "LAYER 2", subtitle: "EARLOBE + EARRING ANCHOR DETECTION", status: anchor.status, detail: anchor.detail || "Locate both points" },
      { title: "LAYER 3", subtitle: "PLACEMENT VALIDATION", status: placement.status, detail: placement.detail || "PASS / WARNING / FAIL" },
    ];
  }
  const step = (name: string) => status?.steps.find((item) => item.name === name);
  const layer2 = combineStepStatus(step("earlobe_detection")?.status, step("earring_detection")?.status);
  return [
    {
      title: "LAYER 1",
      subtitle: "FRAME SELECTION",
      status: step("frame_selection")?.status || "NOT_RUN",
      detail: step("frame_selection")?.detail || "Select representative frames",
    },
    {
      title: "LAYER 2",
      subtitle: "EARLOBE + EARRING ANCHOR DETECTION",
      status: layer2,
      detail: [step("earlobe_detection")?.detail, step("earring_detection")?.detail].filter(Boolean).join(" ") || "Locate both points",
    },
    {
      title: "LAYER 3",
      subtitle: "PLACEMENT VALIDATION",
      status: step("placement_validation")?.status || "NOT_RUN",
      detail: step("placement_validation")?.detail || "PASS / WARNING / FAIL",
    },
  ];
}

function combineStepStatus(...values: Array<string | undefined>) {
  if (values.some((value) => value === "FAIL")) return "FAIL";
  if (values.some((value) => value === "RUNNING")) return "RUNNING";
  if (values.some((value) => value === "WARNING")) return "WARNING";
  if (values.every((value) => value === "PASS")) return "PASS";
  if (values.some((value) => value === "WAITING")) return "WAITING";
  return "NOT_RUN";
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
