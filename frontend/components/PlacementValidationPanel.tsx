import { QaReport } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

type ComponentView = {
  status?: string;
};

export function PlacementValidationPanel({ report }: { report: QaReport }) {
  const panel = report.placement_validation;
  if (!panel || (report.jewelry_type !== "earring" && report.jewelry_type !== "necklace")) {
    return null;
  }
  const components = panel.components || {};
  const isEarring = report.jewelry_type === "earring";

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 text-sm">
      <p className="mb-3 text-xs uppercase tracking-[0.2em] text-zinc-500">
        {isEarring ? "Earring" : "Necklace"}
      </p>

      {isEarring ? (
        <div className="grid gap-3 md:grid-cols-2">
          <ComponentCard title="Left" data={components.left_earring} />
          <ComponentCard title="Right" data={components.right_earring} />
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <ComponentCard title="Necklace center" data={components.necklace_center} />
          <ComponentCard title="Left anchor" data={components.left_anchor} />
          <ComponentCard title="Right anchor" data={components.right_anchor} />
          <ComponentCard title="Pendant alignment" data={components.pendant_alignment} />
        </div>
      )}
    </div>
  );
}

function ComponentCard({ title, data }: { title: string; data?: ComponentView }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded border border-zinc-800 px-3 py-3">
      <p className="font-medium text-zinc-200">{title}</p>
      <StatusBadge status={data?.status} />
    </div>
  );
}
