"use client";

import { useEffect, useState } from "react";
import { api, ReferenceRecord } from "@/lib/api";
import { Card, Field, inputClass } from "./Shell";

export function ReferenceUpload({
  selectedId,
  onSelect,
}: {
  selectedId?: string;
  onSelect?: (reference: ReferenceRecord) => void;
}) {
  const [items, setItems] = useState<ReferenceRecord[]>([]);
  const [side, setSide] = useState("left");
  const [error, setError] = useState("");
  const [anchorTarget, setAnchorTarget] = useState<string | null>(null);
  const [anchors, setAnchors] = useState({
    earlobe_x: "0.42",
    earlobe_y: "0.55",
    earring_x: "0.43",
    earring_y: "0.57",
    ear_width: "0.06",
    ear_height: "0.1",
  });

  async function refresh() {
    setItems(await api.references());
  }

  useEffect(() => {
    refresh().catch((exc: Error) => setError(exc.message));
  }, []);

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setError("");
    try {
      const created = await api.uploadReference(file, side);
      await refresh();
      onSelect?.(created);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Upload failed");
    }
  }

  async function saveAnchors(id: string) {
    setError("");
    try {
      const updated = await api.setReferenceAnchors(id, {
        side,
        earlobe_x: Number(anchors.earlobe_x),
        earlobe_y: Number(anchors.earlobe_y),
        earring_x: Number(anchors.earring_x),
        earring_y: Number(anchors.earring_y),
        ear_width: Number(anchors.ear_width),
        ear_height: Number(anchors.ear_height),
      });
      setAnchorTarget(null);
      await refresh();
      onSelect?.(updated);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Unable to save anchors");
    }
  }

  return (
    <Card title="Reference Images">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Side for analysis">
          <select className={inputClass} value={side} onChange={(event) => setSide(event.target.value)}>
            <option value="left">Left</option>
            <option value="right">Right</option>
          </select>
        </Field>
        <label className="rounded bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-950">
          Upload Reference Image
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(event) => onUpload(event.target.files?.[0])}
          />
        </label>
      </div>
      {error ? <p className="mb-3 text-sm text-red-400">{error}</p> : null}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <article key={item.id} className={`rounded border p-3 ${selectedId === item.id ? "border-zinc-300" : "border-zinc-800"}`}>
            <button type="button" className="block w-full text-left" onClick={() => onSelect?.(item)}>
              <img src={api.asset(item.image_url)} alt={item.filename} className="h-36 w-full rounded object-cover" />
              <p className="mt-2 text-sm text-zinc-100">{item.filename}</p>
              <p className="text-xs text-zinc-500">
                {item.id} · {item.width}×{item.height}
              </p>
            </button>
            <p className="mt-2 text-xs text-zinc-400">
              {item.normalized_distance != null
                ? `Relative distance ${item.normalized_distance.toFixed(3)}`
                : item.analysis_error || "Reference geometry was not derived."}
            </p>
            <div className="mt-3 flex gap-2">
              <button type="button" className="text-xs text-zinc-300 underline" onClick={() => onSelect?.(item)}>
                Select as active reference
              </button>
              <button type="button" className="text-xs text-zinc-400 underline" onClick={() => setAnchorTarget(item.id)}>
                Set anchors
              </button>
              <button
                type="button"
                className="text-xs text-red-400 underline"
                onClick={() => api.deleteReference(item.id).then(refresh)}
              >
                Delete
              </button>
            </div>
            {anchorTarget === item.id ? (
              <div className="mt-3 grid grid-cols-2 gap-2">
                {Object.entries(anchors).map(([key, value]) => (
                  <label key={key} className="text-xs text-zinc-500">
                    {key}
                    <input
                      className={inputClass}
                      value={value}
                      onChange={(event) => setAnchors({ ...anchors, [key]: event.target.value })}
                    />
                  </label>
                ))}
                <button type="button" className="col-span-2 rounded border border-zinc-600 py-1 text-xs" onClick={() => saveAnchors(item.id)}>
                  Save normalized anchors
                </button>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </Card>
  );
}
