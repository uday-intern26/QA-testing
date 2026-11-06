"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, ApplicationRecord, TestRecord } from "@/lib/api";
import { Card, Field, inputClass } from "./Shell";

type JewelryType = "earring" | "necklace" | "bracelet" | "ring" | "bangle";
type SideMode = "ear" | "side" | "center";

type TypeProfile = {
  value: JewelryType;
  label: string;
  name: string;
  jewelryId: string;
  sideMode: SideMode;
  sideLabel: string;
  attachment: string;
  bodyPoint: string;
  jewelLabel: string;
};

const TYPE_PROFILES: Record<JewelryType, TypeProfile> = {
  earring: {
    value: "earring",
    label: "Earring",
    name: "Try-on URL earring on earlobe",
    jewelryId: "Gold Diamond Bezel Stud Earring",
    sideMode: "ear",
    sideLabel: "Ear visible in the video",
    attachment: "Earlobe placement zone",
    bodyPoint: "earlobe",
    jewelLabel: "earring",
  },
  necklace: {
    value: "necklace",
    label: "Necklace",
    name: "Try-on URL necklace on neck",
    jewelryId: "Gold Pendant Necklace",
    sideMode: "center",
    sideLabel: "Attachment check",
    attachment: "Neck / chest placement",
    bodyPoint: "neck",
    jewelLabel: "necklace",
  },
  bracelet: {
    value: "bracelet",
    label: "Bracelet",
    name: "Try-on URL bracelet on wrist",
    jewelryId: "Gold Chain Bracelet",
    sideMode: "side",
    sideLabel: "Wrist visible in the video",
    attachment: "Wrist placement",
    bodyPoint: "wrist",
    jewelLabel: "bracelet",
  },
  ring: {
    value: "ring",
    label: "Ring",
    name: "Try-on URL ring on finger",
    jewelryId: "Gold Diamond Ring",
    sideMode: "side",
    sideLabel: "Hand / side visible in the video",
    attachment: "Finger placement",
    bodyPoint: "hand",
    jewelLabel: "ring",
  },
  bangle: {
    value: "bangle",
    label: "Bangle",
    name: "Try-on URL bangle on wrist",
    jewelryId: "Gold Bangle",
    sideMode: "side",
    sideLabel: "Wrist visible in the video",
    attachment: "Wrist placement",
    bodyPoint: "wrist",
    jewelLabel: "bangle",
  },
};

const TYPE_ORDER: JewelryType[] = ["earring", "necklace", "bracelet", "ring", "bangle"];

const SHARED_DEFAULTS = {
  capture_fps: 5,
  capture_duration_seconds: 6,
  minimum_confidence: 0.5,
  pass_threshold: 0.1,
  fail_threshold: 0.15,
  minimum_pass_rate: 0.95,
  maximum_consecutive_failures: 2,
};

/** Numeric defaults applied only when that jewellery type is selected. */
const TYPE_NUMERIC_DEFAULTS: Record<JewelryType, typeof SHARED_DEFAULTS> = {
  earring: {
    capture_fps: 10,
    capture_duration_seconds: 6,
    minimum_confidence: 0.8,
    pass_threshold: 0.08,
    fail_threshold: 0.15,
    minimum_pass_rate: 0.95,
    maximum_consecutive_failures: 2,
  },
  necklace: {
    capture_fps: 10,
    capture_duration_seconds: 6,
    minimum_confidence: 0.8,
    pass_threshold: 0.1,
    fail_threshold: 0.15,
    minimum_pass_rate: 0.95,
    maximum_consecutive_failures: 2,
  },
  bracelet: {
    capture_fps: 10,
    capture_duration_seconds: 6,
    minimum_confidence: 0.8,
    pass_threshold: 0.1,
    fail_threshold: 0.18,
    minimum_pass_rate: 0.95,
    maximum_consecutive_failures: 2,
  },
  ring: {
    capture_fps: 10,
    capture_duration_seconds: 6,
    minimum_confidence: 0.8,
    pass_threshold: 0.08,
    fail_threshold: 0.15,
    minimum_pass_rate: 0.95,
    maximum_consecutive_failures: 2,
  },
  bangle: {
    capture_fps: 10,
    capture_duration_seconds: 6,
    minimum_confidence: 0.8,
    pass_threshold: 0.08,
    fail_threshold: 0.15,
    minimum_pass_rate: 0.95,
    maximum_consecutive_failures: 2,
  },
};

type SelectedFinger = "thumb" | "index" | "middle" | "ring" | "little";

function defaultsFor(type: JewelryType) {
  const profile = TYPE_PROFILES[type];
  return {
    name: profile.name,
    jewelry_id: profile.jewelryId,
    jewelry_type: type,
    ear_side: profile.sideMode === "center" ? "left" : "left",
    selected_finger: "ring" as SelectedFinger,
    ...TYPE_NUMERIC_DEFAULTS[type],
  };
}

const EMPTY = defaultsFor("earring");

function sideSummary(test: TestRecord) {
  const profile = TYPE_PROFILES[test.jewelry_type as JewelryType];
  if (test.jewelry_type === "ring") {
    return `finger ${test.selected_finger || "ring"} · side ${test.ear_side}`;
  }
  if (!profile || profile.sideMode === "center") return profile?.attachment || "center";
  if (profile.sideMode === "ear") return `ear ${test.ear_side}`;
  return `side ${test.ear_side}`;
}

export function TestConfiguration({
  applicationId,
  onCreated,
}: {
  applicationId?: string;
  onCreated?: (test: TestRecord) => void;
}) {
  const [applications, setApplications] = useState<ApplicationRecord[]>([]);
  const [tests, setTests] = useState<TestRecord[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [appId, setAppId] = useState(applicationId || "");
  const [error, setError] = useState("");

  const profile = useMemo(
    () => TYPE_PROFILES[(form.jewelry_type as JewelryType) || "earring"] || TYPE_PROFILES.earring,
    [form.jewelry_type]
  );

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.applications(), api.tests()])
      .then(([apps, existing]) => {
        if (cancelled) return;
        setApplications(apps);
        setTests(existing);
      })
      .catch((exc: Error) => {
        if (!cancelled) setError(exc.message);
      });
    return () => {
      cancelled = true;
    };
  }, [applicationId]);

  useEffect(() => setAppId(applicationId || ""), [applicationId]);

  function update(key: string, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function selectJewelryType(nextType: JewelryType) {
    const next = TYPE_PROFILES[nextType];
    const previous = TYPE_PROFILES[form.jewelry_type as JewelryType];
    const previousNumeric = TYPE_NUMERIC_DEFAULTS[(form.jewelry_type as JewelryType) || "earring"];
    const nextNumeric = TYPE_NUMERIC_DEFAULTS[nextType];
    setForm((current) => {
      const nameStillDefault = !previous || current.name === previous.name || current.name.trim() === "";
      const jewelryStillDefault =
        !previous || current.jewelry_id === previous.jewelryId || current.jewelry_id.trim() === "";
      let earSide = current.ear_side;
      if (next.sideMode === "center") {
        earSide = "left";
      } else if (next.sideMode === "side" && earSide === "both") {
        earSide = "left";
      }
      const keepCustomThresholds =
        Number(current.capture_fps) !== previousNumeric.capture_fps ||
        Number(current.minimum_confidence) !== previousNumeric.minimum_confidence ||
        Number(current.pass_threshold) !== previousNumeric.pass_threshold ||
        Number(current.fail_threshold) !== previousNumeric.fail_threshold;
      return {
        ...current,
        jewelry_type: nextType,
        name: nameStillDefault ? next.name : current.name,
        jewelry_id: jewelryStillDefault ? next.jewelryId : current.jewelry_id,
        ear_side: earSide,
        selected_finger: nextType === "ring" ? current.selected_finger || "ring" : current.selected_finger,
        ...(keepCustomThresholds ? {} : nextNumeric),
      };
    });
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const earSide =
        profile.sideMode === "center"
          ? "left"
          : profile.sideMode === "side" && form.ear_side === "both"
            ? "left"
            : form.ear_side;
      const created = await api.createTest({
        ...form,
        application_id: appId,
        reference_id: null,
        jewelry_id: form.jewelry_id || null,
        ear_side: earSide,
        selected_finger: form.jewelry_type === "ring" ? form.selected_finger || "ring" : null,
        capture_fps: Number(form.capture_fps),
        capture_duration_seconds: Number(form.capture_duration_seconds),
        minimum_confidence: Number(form.minimum_confidence),
        pass_threshold: Number(form.pass_threshold),
        fail_threshold: Number(form.fail_threshold),
        minimum_pass_rate: Number(form.minimum_pass_rate),
        maximum_consecutive_failures: Number(form.maximum_consecutive_failures),
      });
      setTests(await api.tests());
      onCreated?.(created);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Unable to create the test");
    }
  }

  return (
    <Card title="Test Configuration">
      <p className="mb-3 text-sm text-zinc-400">
        Choose the jewellery type first. Name, jewellery ID example, side options, and placement
        thresholds follow that type ({profile.jewelLabel} on the {profile.bodyPoint}).
      </p>
      <form className="grid gap-3 md:grid-cols-2" onSubmit={onSubmit}>
        <Field label="Jewellery Type">
          <select
            className={inputClass}
            value={form.jewelry_type}
            onChange={(event) => selectJewelryType(event.target.value as JewelryType)}
          >
            {TYPE_ORDER.map((type) => (
              <option key={type} value={type}>
                {TYPE_PROFILES[type].label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Test Name">
          <input className={inputClass} value={form.name} onChange={(event) => update("name", event.target.value)} required />
        </Field>
        <Field label="Application">
          <select className={inputClass} value={appId} onChange={(event) => setAppId(event.target.value)} required>
            <option value="">Select an application</option>
            {applications.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Jewellery ID">
          <input
            className={inputClass}
            placeholder={profile.jewelryId}
            value={form.jewelry_id}
            onChange={(event) => update("jewelry_id", event.target.value)}
          />
        </Field>
        {profile.sideMode === "center" ? (
          <Field label={profile.sideLabel}>
            <input className={inputClass} value={profile.attachment} readOnly />
          </Field>
        ) : (
          <Field label={profile.sideLabel}>
            <select className={inputClass} value={form.ear_side} onChange={(event) => update("ear_side", event.target.value)}>
              <option value="left">Left</option>
              <option value="right">Right</option>
              {profile.sideMode === "ear" ? <option value="both">Both</option> : null}
            </select>
          </Field>
        )}
        {form.jewelry_type === "ring" ? (
          <Field label="Selected Finger">
            <select
              className={inputClass}
              value={form.selected_finger || "ring"}
              onChange={(event) => update("selected_finger", event.target.value)}
            >
              <option value="thumb">Thumb</option>
              <option value="index">Index Finger</option>
              <option value="middle">Middle Finger</option>
              <option value="ring">Ring Finger</option>
              <option value="little">Little Finger</option>
            </select>
          </Field>
        ) : null}
        <Field label="Capture FPS">
          <select className={inputClass} value={form.capture_fps} onChange={(event) => update("capture_fps", event.target.value)}>
            {[1, 2, 5, 10].map((fps) => (
              <option key={fps} value={fps}>
                {fps}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Capture duration (seconds)">
          <input
            className={inputClass}
            type="number"
            value={form.capture_duration_seconds}
            onChange={(event) => update("capture_duration_seconds", event.target.value)}
          />
        </Field>
        <Field label={`Minimum ${profile.bodyPoint} confidence`}>
          <input
            className={inputClass}
            type="number"
            step="0.01"
            value={form.minimum_confidence}
            onChange={(event) => update("minimum_confidence", event.target.value)}
          />
        </Field>
        <Field label={`Pass threshold (${profile.attachment})`}>
          <input
            className={inputClass}
            type="number"
            step="0.01"
            value={form.pass_threshold}
            onChange={(event) => update("pass_threshold", event.target.value)}
          />
        </Field>
        <Field label={`Fail threshold (${profile.jewelLabel} distance)`}>
          <input
            className={inputClass}
            type="number"
            step="0.01"
            value={form.fail_threshold}
            onChange={(event) => update("fail_threshold", event.target.value)}
          />
        </Field>
        <Field label="Minimum Pass Rate">
          <input
            className={inputClass}
            type="number"
            step="0.01"
            value={form.minimum_pass_rate}
            onChange={(event) => update("minimum_pass_rate", event.target.value)}
          />
        </Field>
        <Field label="Maximum Consecutive Failures">
          <input
            className={inputClass}
            type="number"
            value={form.maximum_consecutive_failures}
            onChange={(event) => update("maximum_consecutive_failures", event.target.value)}
          />
        </Field>
        <div className="md:col-span-2 rounded border border-zinc-800 bg-zinc-950/40 px-3 py-2 text-sm text-zinc-400">
          Placement rule for <span className="text-zinc-200">{profile.label}</span>: the {profile.jewelLabel}{" "}
          attachment point must sit on the {profile.bodyPoint} ({profile.attachment.toLowerCase()}).
        </div>
        <div className="md:col-span-2">
          <button className="rounded bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-950" type="submit">
            Save Test Configuration
          </button>
          {error ? <p className="mt-2 text-sm text-red-400">{error}</p> : null}
        </div>
      </form>
      <ul className="mt-4 space-y-2 text-sm text-zinc-400">
        {tests.map((test) => (
          <li key={test.id} className="flex items-center justify-between gap-3">
            <button type="button" className="text-left underline" onClick={() => onCreated?.(test)}>
              <span className="text-zinc-200">
                {test.id} · {test.name}
              </span>
              <span className="mt-0.5 block text-xs text-zinc-500">
                {test.jewelry_type}
                {test.jewelry_id ? ` · ${test.jewelry_id}` : ""} · {sideSummary(test)}
              </span>
            </button>
            <button
              type="button"
              className="rounded border border-red-900 px-2 py-1 text-xs text-red-300 hover:bg-red-950"
              onClick={async () => {
                if (!window.confirm(`Delete test ${test.name} and all of its runs?`)) return;
                try {
                  await api.deleteTest(test.id);
                  setTests(await api.tests());
                } catch (exc) {
                  setError(exc instanceof Error ? exc.message : "Delete failed");
                }
              }}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
