"use client";

import { FormEvent, useEffect, useState } from "react";
import { Card } from "@/components/Shell";
import { useTheme } from "@/components/ThemeProvider";
import {
  DEFAULT_GENERAL_SETTINGS,
  loadGeneralSettings,
  resetGeneralSettings,
  saveGeneralSettings,
  type GeneralSettings,
  type ThemeMode,
} from "@/lib/generalSettings";

const THEME_OPTIONS: { value: ThemeMode; label: string; detail: string }[] = [
  { value: "light", label: "Light Mode", detail: "Bright surfaces for daytime use" },
  { value: "dark", label: "Dark Mode", detail: "Default QA console look" },
  { value: "system", label: "System Default", detail: "Follow OS theme preference" },
];

export function GeneralSettingsForm() {
  const { setTheme, refreshFromStorage } = useTheme();
  const [settings, setSettings] = useState<GeneralSettings>(() => structuredClone(DEFAULT_GENERAL_SETTINGS));
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    const loaded = loadGeneralSettings();
    setSettings(loaded);
    setTheme(loaded.appearance.theme);
    setReady(true);
  }, [setTheme]);

  function selectTheme(theme: ThemeMode) {
    setSettings((current) => ({ ...current, appearance: { theme } }));
    setTheme(theme);
  }

  function onSave(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    setBusy(true);
    try {
      saveGeneralSettings(settings);
      setTheme(settings.appearance.theme);
      refreshFromStorage();
      setMessage({ type: "success", text: "Appearance saved. It will stay after refresh." });
    } catch {
      setMessage({ type: "error", text: "Unable to save appearance. Check browser storage permissions." });
    } finally {
      setBusy(false);
    }
  }

  function onReset() {
    const confirmed = window.confirm("Reset appearance to the default dark theme?");
    if (!confirmed) return;
    setBusy(true);
    try {
      const next = resetGeneralSettings();
      setSettings(next);
      setTheme(next.appearance.theme);
      refreshFromStorage();
      setMessage({ type: "success", text: "Appearance restored to dark mode." });
    } catch {
      setMessage({ type: "error", text: "Unable to reset appearance." });
    } finally {
      setBusy(false);
    }
  }

  if (!ready) {
    return <p className="text-sm text-[var(--muted)]">Loading settings…</p>;
  }

  return (
    <form className="space-y-5" onSubmit={onSave}>
      {message ? (
        <p
          className={`rounded border px-3 py-2 text-sm ${
            message.type === "success"
              ? "border-emerald-800 bg-emerald-950/40 text-emerald-300"
              : "border-red-900 bg-red-950/40 text-red-300"
          }`}
          role="status"
        >
          {message.text}
        </p>
      ) : null}

      <Card title="Appearance Settings">
        <div className="grid gap-3 md:grid-cols-3">
          {THEME_OPTIONS.map((option) => {
            const active = settings.appearance.theme === option.value;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => selectTheme(option.value)}
                className={`rounded border px-3 py-3 text-left transition ${
                  active
                    ? "border-emerald-700 bg-emerald-950/30 text-[var(--text)]"
                    : "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--muted)] hover:border-zinc-500"
                }`}
              >
                <p className="text-sm font-medium">{option.label}</p>
                <p className="mt-1 text-xs opacity-80">{option.detail}</p>
              </button>
            );
          })}
        </div>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-950 disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save Changes"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onReset}
          className="rounded border border-red-900 px-4 py-2 text-sm text-red-300 hover:bg-red-950 disabled:opacity-50"
        >
          Reset to Default
        </button>
      </div>
    </form>
  );
}
