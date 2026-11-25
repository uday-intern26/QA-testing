"use client";

import { GeneralSettingsForm } from "@/components/GeneralSettingsForm";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <header>
        <h2 className="text-2xl font-semibold text-[var(--text)]">Settings</h2>
        <p className="mt-2 max-w-3xl text-sm text-[var(--muted)]">Choose light, dark, or the system appearance.</p>
      </header>
      <GeneralSettingsForm />
    </div>
  );
}
