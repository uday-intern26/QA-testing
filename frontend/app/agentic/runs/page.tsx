"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { Card, Field, inputClass } from "@/components/Shell";
import { StatusPill } from "@/components/agentic/StatusPill";
import { agenticApi } from "@/lib/agentic/api";
import type { RunPage, ServiceInfo } from "@/lib/agentic/types";

const presets = [
  { label: "Healthy mock", url: "http://127.0.0.1:8091" },
  { label: "Defective mock", url: "http://127.0.0.1:8092" },
];

export default function AgenticRunsPage() {
  const router = useRouter();
  const [services, setServices] = useState<ServiceInfo[]>([]);
  const [runs, setRuns] = useState<RunPage | null>(null);
  const [service, setService] = useState("recommendation");
  const [target, setTarget] = useState(presets[0].url);
  const [tenant, setTenant] = useState("store_001");
  const [model, setModel] = useState("v2");
  const [maxScenarios, setMaxScenarios] = useState(8);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadRuns = () => {
    agenticApi<RunPage>("/qa/runs?limit=20")
      .then(setRuns)
      .catch((reason: Error) => setError(reason.message));
  };

  useEffect(() => {
    agenticApi<{ services: ServiceInfo[] }>("/qa/services")
      .then((body) => setServices(body.services))
      .catch((reason: Error) => setError(reason.message));
    loadRuns();
  }, []);

  async function start(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await agenticApi<{ run_id: string }>("/qa/runs", {
        method: "POST",
        body: JSON.stringify({
          service,
          target_url: target,
          tenant,
          model_version: model,
          max_scenarios: maxScenarios,
          async_execution: false,
        }),
      });
      router.push(`/agentic/runs/${created.run_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run failed");
      setBusy(false);
      loadRuns();
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Agentic QA</p>
        <h2 className="mt-1 text-2xl font-semibold text-zinc-100">Runs</h2>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Execute contract scenarios against an allowlisted target. Use the healthy or defective local mocks for a full demo.
        </p>
      </header>

      {error ? <div className="rounded border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-200">{error}</div> : null}

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <Card title="Start a run">
          <form className="space-y-3" onSubmit={start}>
            <div className="flex flex-wrap gap-2">
              {presets.map((preset) => (
                <button
                  key={preset.url}
                  type="button"
                  onClick={() => setTarget(preset.url)}
                  className={`rounded border px-3 py-1.5 text-xs ${
                    target === preset.url
                      ? "border-zinc-400 bg-zinc-800 text-zinc-100"
                      : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <Field label="Service">
              <select className={inputClass} value={service} onChange={(event) => setService(event.target.value)}>
                {services.map((item) => (
                  <option key={item.service} value={item.service}>
                    {item.title}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Target URL">
              <input className={inputClass} value={target} onChange={(event) => setTarget(event.target.value)} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Tenant">
                <input className={inputClass} value={tenant} onChange={(event) => setTenant(event.target.value)} />
              </Field>
              <Field label="Model">
                <input className={inputClass} value={model} onChange={(event) => setModel(event.target.value)} />
              </Field>
            </div>
            <Field label="Maximum scenarios">
              <input
                className={inputClass}
                type="number"
                min={1}
                max={40}
                value={maxScenarios}
                onChange={(event) => setMaxScenarios(Number(event.target.value))}
              />
            </Field>
            <button type="submit" disabled={busy} className="rounded bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-950 disabled:opacity-50">
              {busy ? "Executing…" : "Execute run"}
            </button>
            {busy ? <p className="text-xs text-zinc-500">Calling the target and scoring each scenario…</p> : null}
          </form>
        </Card>

        <Card title="History">
          {runs && runs.items.length === 0 ? <p className="text-sm text-zinc-500">No runs have been stored yet.</p> : null}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="pb-2 pr-3">Run</th>
                  <th className="pb-2 pr-3">Status</th>
                  <th className="pb-2 pr-3">Passed</th>
                  <th className="pb-2">Failed</th>
                </tr>
              </thead>
              <tbody>
                {runs?.items.map((run) => (
                  <tr key={run.run_id} className="border-t border-zinc-800">
                    <td className="py-2 pr-3">
                      <Link href={`/agentic/runs/${run.run_id}`} className="font-mono text-sm hover:text-white">
                        {run.run_id}
                      </Link>
                      <div className="text-xs text-zinc-500">
                        {run.service} · {run.model_version}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <StatusPill value={run.status} />
                    </td>
                    <td className="py-2 pr-3">{run.summary?.passed ?? "—"}</td>
                    <td className="py-2">{run.summary?.failed ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
