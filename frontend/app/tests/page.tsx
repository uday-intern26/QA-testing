"use client";

import { TestConfiguration } from "@/components/TestConfiguration";

export default function TestsPage() {
  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-semibold">Test Configuration</h2>
      <p className="text-sm text-zinc-400">Set placement options for the next run. Past configurations are not listed here.</p>
      <TestConfiguration />
    </div>
  );
}
