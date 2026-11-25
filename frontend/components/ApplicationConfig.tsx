"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApplicationRecord, CatalogCategory, ValidationResult } from "@/lib/api";
import { Card, Field, inputClass } from "./Shell";
import { StatusBadge } from "./StatusBadge";

export function ApplicationConfig({
  selectedId,
  listVersion = 0,
  username: usernameProp,
  password: passwordProp,
  onSelect,
  onReady,
  onUsernameChange,
  onPasswordChange,
}: {
  selectedId?: string;
  listVersion?: number;
  username?: string;
  password?: string;
  onSelect?: (application: ApplicationRecord) => void;
  onReady?: (application: ApplicationRecord, catalog: CatalogCategory[]) => void;
  onUsernameChange?: (value: string) => void;
  onPasswordChange?: (value: string) => void;
}) {
  const [items, setItems] = useState<ApplicationRecord[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [localUsername, setLocalUsername] = useState("");
  const [localPassword, setLocalPassword] = useState("");
  const [faceFile, setFaceFile] = useState<File | null>(null);
  const [savedVideo, setSavedVideo] = useState(false);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusNote, setStatusNote] = useState("");
  const openedKey = useRef("");
  const busyRef = useRef(false);
  const username = usernameProp ?? localUsername;
  const password = passwordProp ?? localPassword;
  const setUsername = onUsernameChange ?? setLocalUsername;
  const setPassword = onPasswordChange ?? setLocalPassword;

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
        // Do not auto-fill login — each try-on link needs the credentials entered in Step 1.
      })
      .catch(() => {
        setName("");
        setUrl("");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    refresh().catch((exc: Error) => setError(exc.message));
  }, [listVersion]);

  function choose(item: ApplicationRecord) {
    setName(item.name);
    setUrl(item.url || "");
    // Prefill saved username only as a hint; always clear password (never stored, per-link).
    setUsername(item.username || "");
    setPassword("");
    // Camera uses only the file chosen in the Face video input for this open.
    setFaceFile(null);
    setSavedVideo(Boolean(item.video_path));
    setValidation(null);
    setStatusNote("");
    openedKey.current = "";
    onSelect?.(item);
  }

  async function openTryOn(force = false) {
    const trimmedName = name.trim() || "AIJewel Amplify";
    const trimmedUrl = url.trim();
    const trimmedUser = username.trim();
    const trimmedPass = password;
    if (!trimmedUrl) {
      setError("Enter the try-on link.");
      return;
    }
    if (!trimmedUser || !trimmedPass) {
      setError("Enter the username and password for this try-on link. Each link has its own login.");
      return;
    }
    if (!faceFile) {
      setError("Choose the face video to upload. Only that video is used as the try-on camera.");
      return;
    }
    const key = `${trimmedUrl}|${trimmedUser}|${faceFile.name}|${faceFile.size}|${faceFile.lastModified}`;
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
          username: trimmedUser || null,
        });
      } else if (trimmedUser && record.username !== trimmedUser) {
        record = await api.updateApplication(record.id, {
          url: trimmedUrl,
          username: trimmedUser,
        });
      }
      // Always upload the file chosen in the form so the camera is exactly that video.
      record = await api.uploadFaceVideo(record.id, faceFile);
      setSavedVideo(true);
      const checked = { ...record, name: trimmedName, url: trimmedUrl, username: trimmedUser || null };
      onSelect?.(checked);
      await refresh();
      // Always login with the Step 1 fields for this link — never a hardcoded default.
      const result = await api.validateApplication({
        url: trimmedUrl,
        name: trimmedName,
        type: "web",
        application_id: record.id,
        username: trimmedUser,
        password: trimmedPass,
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
            />
          </Field>
          <Field label="Username">
            <input
              className={inputClass}
              type="text"
              autoComplete="username"
              placeholder="Login for this try-on link"
              value={username}
              onChange={(event) => {
                openedKey.current = "";
                setUsername(event.target.value);
              }}
              required
            />
          </Field>
          <Field label="Password">
            <input
              className={inputClass}
              type="password"
              autoComplete="current-password"
              placeholder="Password for this try-on link"
              value={password}
              onChange={(event) => {
                openedKey.current = "";
                setPassword(event.target.value);
              }}
              required
            />
          </Field>
          <Field label="Face video (no jewelry worn)">
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
              {faceFile
                ? `Camera will use only “${faceFile.name}”. Click Open try-on & camera to apply it.`
                : savedVideo
                  ? "Choose the face video file again. Only the video you upload is used as the camera."
                  : "Upload a clear face/body video with no jewelry. Only that file becomes the try-on camera."}
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
            Each try-on link has its own login. Enter the username and password for this link in Step 1 —
            those values are used for Open try-on and for the test run. The password is never stored.
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
