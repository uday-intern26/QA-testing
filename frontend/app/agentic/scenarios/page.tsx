"use client";

import { FormEvent, useEffect, useState } from "react";

import { Card, Field, inputClass } from "@/components/Shell";
import { StatusPill } from "@/components/agentic/StatusPill";
import { agenticApi } from "@/lib/agentic/api";
import type { Scenario, ServiceInfo } from "@/lib/agentic/types";

type Generated = {
  service: string;
  count: number;
  pairwise: { pairs_total?: number; pairs_covered?: number; percent?: number };
  scenarios: Scenario[];
};

export default function AgenticScenariosPage() {
  const [services, setServices] = useState<ServiceInfo[]>([]);
  const [service, setService] = useState("recommendation");
  const [tenant, setTenant] = useState("store_001");
  const [model, setModel] = useState("v2");
  const [maxScenarios, setMaxScenarios] = useState(12);
  const [generated, setGenerated] = useState<Generated | null>(null);
  const [saved, setSaved] = useState<Scenario[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    agenticApi<{ services: ServiceInfo[] }>("/qa/services")
      .then((body) => setServices(body.services))
      .catch((reason: Error) => setError(reason.message));
    agenticApi<{ items: Scenario[] }>("/qa/scenarios?limit=40")
      .then((body) => setSaved(body.items))
      .catch(() => undefined);
  }, []);

  async function generate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = await agenticApi<Generated>("/qa/scenarios/generate", {
        method: "POST",
        body: JSON.stringify({
          service,
          tenant,
          model_version: model,
          max_scenarios: maxScenarios,
          persist: true,
        }),
      });
      setGenerated(body);
      const listing = await agenticApi<{ items: Scenario[] }>(
        `/qa/scenarios?limit=40&service=${encodeURIComponent(service)}`,
      );
      setSaved(listing.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  }

  const rows = generated?.scenarios ?? saved;
  const coverage = generated?.pairwise.percent;

  return (
    <div className="space-y-6">
      <header>
        <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Agentic QA</p>
        <h2 className="mt-1 text-2xl font-semibold text-zinc-100">Scenarios</h2>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Positive, negative, and boundary cases come from the contract. Pairwise coverage is calculated in Python.
        </p>
      </header>

      {error ? <div className="rounded border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-200">{error}</div> : null}

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card title="Generate">
          <form className="space-y-3" onSubmit={generate}>
            <Field label="Service">
              <select className={inputClass} value={service} onChange={(event) => setService(event.target.value)}>
                {services.map((item) => (
                  <option key={item.service} value={item.service}>
                    {item.title}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Tenant">
              <input className={inputClass} value={tenant} onChange={(event) => setTenant(event.target.value)} />
            </Field>
            <Field label="Model version">
              <input className={inputClass} value={model} onChange={(event) => setModel(event.target.value)} />
            </Field>
            <Field label="Maximum scenarios">
              <input
                className={inputClass}
                type="number"
                min={1}
                max={100}
                value={maxScenarios}
                onChange={(event) => setMaxScenarios(Number(event.target.value))}
              />
            </Field>
            <button type="submit" disabled={busy} className="rounded bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-950 disabled:opacity-50">
              {busy ? "Generating…" : "Generate scenarios"}
            </button>
            {coverage !== undefined ? (
              <div>
                <p className="text-xs text-zinc-500">Pairwise coverage {coverage}%</p>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-zinc-800">
                  <div className="h-full bg-zinc-300" style={{ width: `${Math.max(0, Math.min(100, coverage))}%` }} />
                </div>
              </div>
            ) : null}
          </form>
        </Card>

        <Card title={generated ? `${generated.count} generated` : "Saved scenarios"}>
          {rows.length === 0 ? <p className="text-sm text-zinc-500">Generate a set to see cases here.</p> : null}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="pb-2 pr-3">ID</th>
                  <th className="pb-2 pr-3">Call</th>
                  <th className="pb-2 pr-3">Priority</th>
                  <th className="pb-2">Technique</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((scenario) => (
                  <tr key={scenario.test_id} className="border-t border-zinc-800 align-top">
                    <td className="py-2 pr-3">
                      <div className="font-mono text-xs">{scenario.test_id}</div>
                      <div className="text-xs text-zinc-500">{scenario.objective}</div>
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {scenario.method} {scenario.endpoint}
                    </td>
                    <td className="py-2 pr-3">
                      <StatusPill value={scenario.priority} />
                    </td>
                    <td className="py-2">{scenario.technique}</td>
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
