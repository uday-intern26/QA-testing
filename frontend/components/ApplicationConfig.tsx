"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApplicationRecord, CatalogCategory, ValidationResult } from "@/lib/api";
import { Card, Field, inputClass } from "./Shell";
import { StatusBadge } from "./StatusBadge";

export function ApplicationConfig({
  selectedId,
  listVersion = 0,
  onSelect,
  onReady,
}: {
  selectedId?: string;
  listVersion?: number;
  onSelect?: (application: ApplicationRecord) => void;
  onReady?: (application: ApplicationRecord, catalog: CatalogCategory[]) => void;
}) {
  const [items, setItems] = useState<ApplicationRecord[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [faceFile, setFaceFile] = useState<File | null>(null);
  const [savedVideo, setSavedVideo] = useState(false);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusNote, setStatusNote] = useState("");
  const openedKey = useRef("");
  const busyRef = useRef(false);

  async function refresh() {
    const next = await api.applications();
    setItems(next);
    return next;
  }

  useEffect(() => {
    api
      .tryonForm()
      .then((form) => {
        setName(form.name || "");
        setUrl(form.url || "");
      })
      .catch(() => {
        setName("");
        setUrl("");
      });
  }, []);

  useEffect(() => {
    refresh().catch((exc: Error) => setError(exc.message));
  }, [listVersion]);

  function choose(item: ApplicationRecord) {
    setName(item.name);
    setUrl(item.url || "");
    setSavedVideo(Boolean(item.video_path));
    setValidation(null);
    setStatusNote("");
    openedKey.current = "";
    onSelect?.(item);
  }

  async function openTryOn(force = false) {
    const trimmedName = name.trim() || "AIJewel Amplify";
    const trimmedUrl = url.trim();
    if (!trimmedUrl) {
      setError("Enter the try-on link.");
      return;
    }
    if (!faceFile && !savedVideo) {
      setError("Upload a video of the girl wearing no earrings so the camera can turn on.");
      return;
    }
    const key = `${trimmedUrl}|${faceFile?.name || "saved"}`;
    if (!force && (busyRef.current || openedKey.current === key)) {
      return;
    }
    busyRef.current = true;
    openedKey.current = key;
    setBusy(true);
    setError("");
    setValidation(null);
    setStatusNote("Opening the try-on page and turning on the camera…");
    try {
      let record = selectedId ? items.find((item) => item.id === selectedId) : undefined;
      if (!record) {
        record = items.find((item) => item.url === trimmedUrl);
      }
      if (!record) {
        record = await api.createApplication({
          name: trimmedName,
          type: "web",
          url: trimmedUrl,
        });
      }
      if (faceFile) {
        record = await api.uploadFaceVideo(record.id, faceFile);
        setSavedVideo(true);
      }
      const checked = { ...record, name: trimmedName, url: trimmedUrl };
      onSelect?.(checked);
      await refresh();
      const result = await api.validateApplication({
        url: trimmedUrl,
        name: trimmedName,
        type: "web",
        application_id: record.id,
      });
      setValidation(result);
      if (result.status === "success") {
        const savedItems = await refresh();
        const saved = savedItems.find((item) => item.id === (result.application_id || record.id)) || {
          ...checked,
          name: trimmedName,
          url: trimmedUrl,
        };
        onSelect?.(saved);
        const catalog = result.catalog?.length
          ? result.catalog
          : [{ category: "Earrings", items: result.jewelry || [] }];
        onReady?.(saved, catalog);
        setStatusNote("Try-on is open with the camera on. Choose the jewelry type and jewelry ID.");
      } else {
        openedKey.current = "";
        setStatusNote("");
      }
    } catch (exc) {
      openedKey.current = "";
      setStatusNote("");
      setError(exc instanceof Error ? exc.message : "Unable to open the try-on");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  useEffect(() => {
    const trimmedUrl = url.trim();
    const ready = Boolean(trimmedUrl && (faceFile || savedVideo));
    if (!ready || busyRef.current) return;
    const key = `${trimmedUrl}|${faceFile?.name || "saved"}`;
    if (openedKey.current === key) return;
    const timer = window.setTimeout(() => {
      void openTryOn(false);
    }, 900);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, faceFile, savedVideo]);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
      <Card title="Try-on application">
        <div className="space-y-3">
          <Field label="Name">
            <input
              className={inputClass}
              placeholder="Application name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </Field>
          <Field label="Try-on link">
            <input
              className={inputClass}
              placeholder="https://xxxxx.amplifyapp.com/try-on"
              value={url}
              onChange={(event) => {
                openedKey.current = "";
                setUrl(event.target.value);
              }}
              onBlur={() => {
                if (url.trim() && (faceFile || savedVideo)) {
                  void openTryOn(false);
                }
              }}
            />
          </Field>
          <Field label="Face video, no earrings">
            <input
              className={inputClass}
              type="file"
              accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov"
              onChange={(event) => {
                openedKey.current = "";
                setFaceFile(event.target.files?.[0] || null);
                setError("");
              }}
            />
            <p className="mt-1 text-xs text-zinc-500">
              {savedVideo
                ? "A face video is already saved. When the try-on opens, this video is the camera."
                : "This video becomes the try-on camera as soon as the page opens."}
            </p>
          </Field>
          <button
            type="button"
            disabled={busy}
            onClick={() => void openTryOn(true)}
            className="rounded bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-950 disabled:opacity-50"
          >
            {busy ? "Opening try-on & camera…" : "Open try-on & camera"}
          </button>
          <p className="text-xs text-zinc-500">
            After you enter the try-on link and face video, the try-on page opens automatically with the
            camera on.
          </p>
          {statusNote ? <p className="text-sm text-sky-300">{statusNote}</p> : null}
          {error ? <p className="text-sm text-red-400">{error}</p> : null}
          {validation ? (
            <div className="space-y-1 text-sm">
              <StatusBadge status={validation.status === "success" ? "PASS" : "FAIL"} />
              <p className={validation.reachable ? "text-emerald-400" : "text-red-400"}>
                {validation.reachable ? "✓" : "✗"} Application reachable
              </p>
              <p className={validation.application_loaded ? "text-emerald-400" : "text-red-400"}>
                {validation.application_loaded ? "✓" : "✗"} Try-on opened with camera
              </p>
              <p className="text-zinc-400">{validation.message}</p>
              {validation.screenshot_url ? (
                <img src={api.asset(validation.screenshot_url)} alt="Validation screenshot" className="mt-3 max-h-48 rounded border border-zinc-800" />
              ) : null}
            </div>
          ) : null}
        </div>
      </Card>
      <Card title="Saved applications">
        <ul className="space-y-2">
          {items.filter((item) => item.url).map((item) => (
            <li key={item.id} className="flex items-stretch gap-2">
              <button
                type="button"
                onClick={() => choose(item)}
                className={`min-w-0 flex-1 rounded border px-3 py-2 text-left text-sm ${
                  selectedId === item.id ? "border-zinc-400" : "border-zinc-800"
                }`}
              >
                <span className="block text-zinc-100">{item.name}</span>
                <span className="mt-1 block truncate text-xs text-zinc-400">{item.url}</span>
                <span className="text-xs text-zinc-500">
                  {item.id}
                  {item.video_path ? " · face video saved" : ""}
                </span>
              </button>
              <button
                type="button"
                className="rounded border border-red-900 px-3 text-xs text-red-300 hover:bg-red-950"
                onClick={async () => {
                  if (!window.confirm(`Delete application ${item.name}? Related tests and runs will also be removed.`)) {
                    return;
                  }
                  try {
                    await api.deleteApplication(item.id);
                    if (selectedId === item.id) {
                      setName("");
                      setUrl("");
                      setSavedVideo(false);
                      setValidation(null);
                    }
                    await refresh();
                  } catch (exc) {
                    setError(exc instanceof Error ? exc.message : "Delete failed");
                  }
                }}
              >
                Delete
              </button>
            </li>
          ))}
          {!items.some((item) => item.url) ? <li className="text-sm text-zinc-500">No applications saved.</li> : null}
        </ul>
      </Card>
    </div>
  );
}
