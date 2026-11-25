import { StatusBadge } from "./StatusBadge";

interface Layer {
  title: string;
  subtitle: string;
  status: string;
  detail?: string;
}

export function TestLayers({ layers }: { layers: Layer[] }) {
  return (
    <div className="divide-y divide-zinc-800 rounded border border-zinc-800">
      {layers.map((layer) => (
        <div key={layer.title} className="flex items-center justify-between gap-3 px-3 py-2">
          <div className="min-w-0">
            <p className="truncate text-sm text-zinc-200">
              <span className="text-zinc-500">{layer.title}</span>
              <span className="mx-1.5 text-zinc-600">·</span>
              {layer.subtitle}
            </p>
            {layer.detail && layer.status !== "NOT_RUN" ? (
              <p className="truncate text-xs text-zinc-500">{layer.detail}</p>
            ) : null}
          </div>
          <StatusBadge status={layer.status} />
        </div>
      ))}
    </div>
  );
}

export function layerStatus(value: { status: string; detail: string } | string | undefined): {
  status: string;
  detail: string;
} {
  if (!value) return { status: "NOT_RUN", detail: "" };
  if (typeof value === "string") return { status: value, detail: "" };
  return value;
}
