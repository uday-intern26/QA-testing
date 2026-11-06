"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card } from "@/components/Shell";
import { StatusPill } from "@/components/agentic/StatusPill";
import { agenticApi } from "@/lib/agentic/api";
import type { Health, ModelInfo, RunPage, ServiceInfo } from "@/lib/agentic/types";

export default function AgenticBenchPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [services, setServices] = useState<ServiceInfo[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [runs, setRuns] = useState<RunPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      agenticApi<Health>("/health"),
      agenticApi<{ services: ServiceInfo[] }>("/qa/services"),
      agenticApi<{ models: ModelInfo[] }>("/qa/models"),
      agenticApi<RunPage>("/qa/runs?limit=5"),
    ])
      .then(([nextHealth, nextServices, nextModels, nextRuns]) => {
        setHealth(nextHealth);
        setServices(nextServices.services);
        setModels(nextModels.models);
        setRuns(nextRuns);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const passed = runs?.items.reduce((sum, run) => sum + (run.summary?.passed ?? 0), 0) ?? 0;
  const failed = runs?.items.reduce((sum, run) => sum + (run.summary?.failed ?? 0), 0) ?? 0;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Agentic QA</p>
          <h2 className="mt-1 text-2xl font-semibold text-zinc-100">Contract-driven bench</h2>
          <p className="mt-2 max-w-3xl text-sm text-zinc-400">
            Generate and execute black-box API tests from OpenAPI contracts. Pair this with Try-On QA in the same console.
          </p>
        </div>
        <Link href="/agentic/runs" className="rounded bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-950">
          New run
        </Link>
      </header>

      {error ? (
        <div className="rounded border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-200">{error}</div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <p className="text-2xl font-semibold">{health?.status ?? "—"}</p>
          <p className="mt-1 text-xs text-zinc-500">Controller · {health?.checks.database ?? "unknown"}</p>
        </Card>
        <Card>
          <p className="text-2xl font-semibold">{services.length || "—"}</p>
          <p className="mt-1 text-xs text-zinc-500">Loaded services</p>
        </Card>
        <Card>
          <p className="text-2xl font-semibold">{passed}</p>
          <p className="mt-1 text-xs text-zinc-500">Passed in latest runs</p>
        </Card>
        <Card>
          <p className="text-2xl font-semibold">{failed}</p>
          <p className="mt-1 text-xs text-zinc-500">Failed in latest runs</p>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Services">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="pb-2 pr-3">Service</th>
                  <th className="pb-2 pr-3">Ops</th>
                  <th className="pb-2">Auth</th>
                </tr>
              </thead>
              <tbody>
                {services.map((service) => (
                  <tr key={service.service} className="border-t border-zinc-800">
                    <td className="py-2 pr-3">
                      <div className="font-medium text-zinc-200">{service.title}</div>
                      <div className="font-mono text-xs text-zinc-500">{service.service}</div>
                    </td>
                    <td className="py-2 pr-3">{service.operations}</td>
                    <td className="py-2">{service.auth_required_operations ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Models and recent runs">
          <div className="space-y-2">
            {models.map((model) => (
              <div key={`${model.service}-${model.version}`} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-mono text-zinc-400">{model.service}</span>
                <StatusPill value={model.version} />
                <StatusPill value={model.approved ? "approved" : "blocked"} />
              </div>
            ))}
          </div>
          <h3 className="mb-2 mt-6 text-xs uppercase tracking-wide text-zinc-500">Recent runs</h3>
          {runs && runs.items.length === 0 ? <p className="text-sm text-zinc-500">No runs yet.</p> : null}
          <div className="space-y-2">
            {runs?.items.map((run) => (
              <Link key={run.run_id} href={`/agentic/runs/${run.run_id}`} className="flex flex-wrap items-center gap-2 text-sm hover:text-white">
                <span className="font-mono">{run.run_id}</span>
                <StatusPill value={run.status} />
                <span className="text-zinc-500">{run.service}</span>
              </Link>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
