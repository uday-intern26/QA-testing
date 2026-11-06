"use client";

import { FormEvent, useEffect, useState } from "react";

import { Card, Field, inputClass } from "@/components/Shell";
import { agenticApi } from "@/lib/agentic/api";
import type { ServiceInfo } from "@/lib/agentic/types";

export default function AgenticContractsPage() {
  const [services, setServices] = useState<ServiceInfo[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    agenticApi<{ services: ServiceInfo[] }>("/qa/services")
      .then((body) => setServices(body.services))
      .catch((reason: Error) => setError(reason.message));
  };

  useEffect(load, []);

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const saved = await agenticApi<{ service: string; title: string; operations: number }>("/qa/contracts", {
        method: "POST",
        body: form,
      });
      setMessage(`Loaded ${saved.title} as ${saved.service} (${saved.operations} operations).`);
      setFile(null);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Agentic QA</p>
        <h2 className="mt-1 text-2xl font-semibold text-zinc-100">Contracts</h2>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          OpenAPI YAML files describe the AIJewel backends. Upload another contract to register a service. Live keys are redacted before storage.
        </p>
      </header>

      {error ? <div className="rounded border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-200">{error}</div> : null}
      {message ? <div className="rounded border border-emerald-900 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-200">{message}</div> : null}

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card title="Upload YAML">
          <form className="space-y-4" onSubmit={upload}>
            <Field label="Contract file">
              <input
                className={inputClass}
                type="file"
                accept=".yaml,.yml,application/yaml,text/yaml"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </Field>
            <button
              type="submit"
              disabled={!file || busy}
              className="rounded bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-950 disabled:opacity-50"
            >
              {busy ? "Uploading…" : "Register contract"}
            </button>
          </form>
        </Card>

        <Card title="Loaded services">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="pb-2 pr-3">Service</th>
                  <th className="pb-2 pr-3">Version</th>
                  <th className="pb-2 pr-3">Ops</th>
                  <th className="pb-2">Servers</th>
                </tr>
              </thead>
              <tbody>
                {services.map((service) => (
                  <tr key={service.service} className="border-t border-zinc-800 align-top">
                    <td className="py-2 pr-3">
                      <div className="font-medium text-zinc-200">{service.title}</div>
                      <div className="font-mono text-xs text-zinc-500">{service.service}</div>
                    </td>
                    <td className="py-2 pr-3">{service.version}</td>
                    <td className="py-2 pr-3">{service.operations}</td>
                    <td className="py-2 font-mono text-xs text-zinc-400">
                      {(service.servers ?? []).slice(0, 2).map((url) => (
                        <div key={url}>{url}</div>
                      ))}
                      {(service.servers ?? []).length === 0 ? "—" : null}
                    </td>
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
