"use client";

import { FormEvent, useEffect, useState } from "react";
import { Card, Field, inputClass } from "@/components/Shell";
import { useTheme } from "@/components/ThemeProvider";
import {
  DEFAULT_GENERAL_SETTINGS,
  LANGUAGE_OPTIONS,
  TIME_ZONE_OPTIONS,
  clearPasswordHash,
  hashPassword,
  loadGeneralSettings,
  readPasswordHash,
  resetGeneralSettings,
  saveGeneralSettings,
  setPasswordHash,
  validateGeneralSettings,
  validatePasswordChange,
  type GeneralSettings,
  type PasswordForm,
  type ThemeMode,
} from "@/lib/generalSettings";

function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-3">
      <div>
        <p className="text-sm text-[var(--text)]">{label}</p>
        {description ? <p className="mt-0.5 text-xs text-[var(--muted)]">{description}</p> : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
          checked ? "bg-emerald-600" : "bg-zinc-600"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
            checked ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

function PasswordField({
  label,
  value,
  onChange,
  visible,
  onToggleVisible,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  visible: boolean;
  onToggleVisible: () => void;
  autoComplete: string;
}) {
  return (
    <Field label={label}>
      <div className="relative">
        <input
          className={`${inputClass} pr-20`}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
        />
        <button
          type="button"
          className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-[var(--muted)] hover:text-[var(--text)]"
          onClick={onToggleVisible}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
    </Field>
  );
}

export function GeneralSettingsForm() {
  const { setTheme, refreshFromStorage } = useTheme();
  const [settings, setSettings] = useState<GeneralSettings>(() => structuredClone(DEFAULT_GENERAL_SETTINGS));
  const [password, setPassword] = useState<PasswordForm>({
    currentPassword: "",
    newPassword: "",
    confirmPassword: "",
  });
  const [showPasswords, setShowPasswords] = useState({ current: false, next: false, confirm: false });
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    const loaded = loadGeneralSettings();
    setSettings(loaded);
    setTheme(loaded.appearance.theme);
    setReady(true);
  }, [setTheme]);

  function patchAccount<K extends keyof GeneralSettings["account"]>(key: K, value: GeneralSettings["account"][K]) {
    setSettings((current) => ({ ...current, account: { ...current.account, [key]: value } }));
  }

  function patchRegional<K extends keyof GeneralSettings["regional"]>(key: K, value: GeneralSettings["regional"][K]) {
    setSettings((current) => ({ ...current, regional: { ...current.regional, [key]: value } }));
  }

  function patchQa<K extends keyof GeneralSettings["qa"]>(key: K, value: GeneralSettings["qa"][K]) {
    setSettings((current) => ({ ...current, qa: { ...current.qa, [key]: value } }));
  }

  function patchNotification<K extends keyof GeneralSettings["notifications"]>(
    key: K,
    value: GeneralSettings["notifications"][K]
  ) {
    setSettings((current) => ({ ...current, notifications: { ...current.notifications, [key]: value } }));
  }

  function selectTheme(theme: ThemeMode) {
    setSettings((current) => ({ ...current, appearance: { theme } }));
    setTheme(theme);
  }

  async function onSave(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    const validation = validateGeneralSettings(settings);
    if (!validation.ok) {
      setMessage({ type: "error", text: validation.messages.join(" ") });
      return;
    }

    const existingHash = readPasswordHash();
    const wantsPasswordChange = Boolean(
      password.currentPassword || password.newPassword || password.confirmPassword
    );
    if (wantsPasswordChange) {
      const passwordCheck = validatePasswordChange(password, Boolean(existingHash));
      if (!passwordCheck.ok) {
        setMessage({ type: "error", text: passwordCheck.messages.join(" ") });
        return;
      }
      if (existingHash) {
        const currentHash = await hashPassword(password.currentPassword);
        if (currentHash !== existingHash) {
          setMessage({ type: "error", text: "Current password is incorrect." });
          return;
        }
      }
    }

    setBusy(true);
    try {
      saveGeneralSettings(settings);
      setTheme(settings.appearance.theme);
      if (wantsPasswordChange) {
        await setPasswordHash(password.newPassword);
        setPassword({ currentPassword: "", newPassword: "", confirmPassword: "" });
      }
      refreshFromStorage();
      setMessage({
        type: "success",
        text: wantsPasswordChange
          ? "Settings and password saved. Preferences will persist after refresh."
          : "Settings saved. Preferences will persist after refresh.",
      });
    } catch {
      setMessage({ type: "error", text: "Unable to save settings. Check browser storage permissions." });
    } finally {
      setBusy(false);
    }
  }

  function onReset() {
    const confirmed = window.confirm(
      "Reset General Settings to defaults?\n\nThis restores appearance, notifications, regional, and QA preferences. Account profile fields return to defaults. It does not delete applications, tests, runs, reports, or API data."
    );
    if (!confirmed) return;
    setBusy(true);
    try {
      const next = resetGeneralSettings();
      clearPasswordHash();
      setSettings(next);
      setPassword({ currentPassword: "", newPassword: "", confirmPassword: "" });
      setTheme(next.appearance.theme);
      refreshFromStorage();
      setMessage({ type: "success", text: "General Settings restored to defaults." });
    } catch {
      setMessage({ type: "error", text: "Unable to reset settings." });
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

      <Card title="Account Settings">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Username">
            <input
              className={inputClass}
              value={settings.account.username}
              onChange={(event) => patchAccount("username", event.target.value)}
              required
              minLength={2}
              maxLength={80}
            />
          </Field>
          <Field label="Email">
            <input
              className={inputClass}
              type="email"
              value={settings.account.email}
              onChange={(event) => patchAccount("email", event.target.value)}
              required
            />
          </Field>
        </div>
      </Card>

      <Card title="Appearance Settings">
        <div className="grid gap-3 md:grid-cols-3">
          {(
            [
              { value: "light", label: "Light Mode", detail: "Bright surfaces for daytime use" },
              { value: "dark", label: "Dark Mode", detail: "Default QA console look" },
              { value: "system", label: "System Default", detail: "Follow OS theme preference" },
            ] as const
          ).map((option) => {
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

      <Card title="Notification Settings">
        <div className="grid gap-3 md:grid-cols-2">
          <Toggle
            label="Email Notifications"
            description="Send email summaries for important QA events"
            checked={settings.notifications.email}
            onChange={(next) => patchNotification("email", next)}
          />
          <Toggle
            label="In-App Notifications"
            description="Show alerts inside the console"
            checked={settings.notifications.inApp}
            onChange={(next) => patchNotification("inApp", next)}
          />
          <Toggle
            label="Test Execution Notifications"
            description="Notify when a test run starts or finishes"
            checked={settings.notifications.testExecution}
            onChange={(next) => patchNotification("testExecution", next)}
          />
          <Toggle
            label="Failed API Test Alerts"
            description="Highlight failed contract or API checks"
            checked={settings.notifications.failedApiAlerts}
            onChange={(next) => patchNotification("failedApiAlerts", next)}
          />
          <Toggle
            label="System Notifications"
            description="Maintenance and environment notices"
            checked={settings.notifications.system}
            onChange={(next) => patchNotification("system", next)}
          />
        </div>
      </Card>

      <Card title="Language and Regional Settings">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Language">
            <select
              className={inputClass}
              value={settings.regional.language}
              onChange={(event) => patchRegional("language", event.target.value)}
            >
              {LANGUAGE_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Time Zone">
            <select
              className={inputClass}
              value={settings.regional.timeZone}
              onChange={(event) => patchRegional("timeZone", event.target.value)}
            >
              {TIME_ZONE_OPTIONS.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Date Format">
            <select
              className={inputClass}
              value={settings.regional.dateFormat}
              onChange={(event) =>
                patchRegional("dateFormat", event.target.value as GeneralSettings["regional"]["dateFormat"])
              }
            >
              <option value="DD/MM/YYYY">DD/MM/YYYY</option>
              <option value="MM/DD/YYYY">MM/DD/YYYY</option>
              <option value="YYYY-MM-DD">YYYY-MM-DD</option>
            </select>
          </Field>
          <Field label="Time Format">
            <select
              className={inputClass}
              value={settings.regional.timeFormat}
              onChange={(event) =>
                patchRegional("timeFormat", event.target.value as GeneralSettings["regional"]["timeFormat"])
              }
            >
              <option value="12h">12-hour</option>
              <option value="24h">24-hour</option>
            </select>
          </Field>
        </div>
      </Card>

      <Card title="Security Settings">
        <p className="mb-3 text-xs text-[var(--muted)]">
          Passwords are validated locally and stored only as a one-way hash in this browser. They are never logged or
          sent to the API.
        </p>
        <div className="grid gap-3 md:grid-cols-3">
          <PasswordField
            label="Current Password"
            value={password.currentPassword}
            onChange={(value) => setPassword((current) => ({ ...current, currentPassword: value }))}
            visible={showPasswords.current}
            onToggleVisible={() => setShowPasswords((current) => ({ ...current, current: !current.current }))}
            autoComplete="current-password"
          />
          <PasswordField
            label="New Password"
            value={password.newPassword}
            onChange={(value) => setPassword((current) => ({ ...current, newPassword: value }))}
            visible={showPasswords.next}
            onToggleVisible={() => setShowPasswords((current) => ({ ...current, next: !current.next }))}
            autoComplete="new-password"
          />
          <PasswordField
            label="Confirm New Password"
            value={password.confirmPassword}
            onChange={(value) => setPassword((current) => ({ ...current, confirmPassword: value }))}
            visible={showPasswords.confirm}
            onToggleVisible={() => setShowPasswords((current) => ({ ...current, confirm: !current.confirm }))}
            autoComplete="new-password"
          />
        </div>
      </Card>

      <Card title="QA Preferences">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Default Testing Environment">
            <select
              className={inputClass}
              value={settings.qa.defaultEnvironment}
              onChange={(event) =>
                patchQa("defaultEnvironment", event.target.value as GeneralSettings["qa"]["defaultEnvironment"])
              }
            >
              <option value="local">Local</option>
              <option value="development">Development</option>
              <option value="qa">QA</option>
              <option value="staging">Staging</option>
            </select>
          </Field>
          <Field label="Default Response Format">
            <select
              className={inputClass}
              value={settings.qa.responseFormat}
              onChange={(event) =>
                patchQa("responseFormat", event.target.value as GeneralSettings["qa"]["responseFormat"])
              }
            >
              <option value="json">JSON</option>
              <option value="xml">XML</option>
            </select>
          </Field>
          <Field label="Default API Base URL">
            <input
              className={inputClass}
              value={settings.qa.apiBaseUrl}
              onChange={(event) => patchQa("apiBaseUrl", event.target.value)}
              placeholder="http://127.0.0.1:8000/api/v1"
            />
          </Field>
          <Field label="Default Request Timeout (ms)">
            <input
              className={inputClass}
              type="number"
              min={1000}
              max={300000}
              step={1000}
              value={settings.qa.requestTimeoutMs}
              onChange={(event) => patchQa("requestTimeoutMs", Number(event.target.value))}
            />
          </Field>
          <Toggle
            label="API Request Logging"
            description="Keep request/response logs for debugging"
            checked={settings.qa.apiRequestLogging}
            onChange={(next) => patchQa("apiRequestLogging", next)}
          />
          <Toggle
            label="Automatic Test Execution"
            description="Start eligible tests without a manual click"
            checked={settings.qa.automaticTestExecution}
            onChange={(next) => patchQa("automaticTestExecution", next)}
          />
          <Toggle
            label="Detailed Error Messages"
            description="Show expanded failure detail in the console"
            checked={settings.qa.detailedErrorMessages}
            onChange={(next) => patchQa("detailedErrorMessages", next)}
          />
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
