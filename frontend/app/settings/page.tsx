"use client";

import { GeneralSettingsForm } from "@/components/GeneralSettingsForm";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <header>
        <h2 className="text-2xl font-semibold text-[var(--text)]">Settings</h2>
        <p className="mt-2 max-w-3xl text-sm text-[var(--muted)]">
          Account, appearance, notifications, regional formats, security, and QA preferences.
        </p>
      </header>
      <GeneralSettingsForm />
    </div>
  );
}
