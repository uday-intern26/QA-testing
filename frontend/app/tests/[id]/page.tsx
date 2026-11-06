"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, QaReport, TestRecord } from "@/lib/api";
import { FrameViewer } from "@/components/FrameViewer";
import { PlacementResult } from "@/components/PlacementResult";
import { ResultSummary } from "@/components/ResultSummary";
import { FrameRow } from "@/lib/api";

export default function TestDetailPage() {
  const params = useParams<{ id: string }>();
  const [test, setTest] = useState<TestRecord | null>(null);
  const [report, setReport] = useState<QaReport | null>(null);
  const [active, setActive] = useState<FrameRow | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const id = params.id;
    api.getTest(id)
      .then(setTest)
      .catch((exc: Error) => setError(exc.message));
    api.results(id)
      .then((result) => {
        setReport(result);
        setActive(result.frames.find((frame) => frame.status === "FAIL") || result.frames[0] || null);
      })
      .catch(() => setReport(null));
  }, [params.id]);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">{test?.name || params.id}</h2>
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      {test ? (
        <dl className="grid gap-2 text-sm text-zinc-300 md:grid-cols-2">
          <div>Application: {test.application_id}</div>
          <div>Reference: {test.reference_id || "none"}</div>
          <div>Jewellery: {test.jewelry_id || "unspecified"} · {test.jewelry_type}</div>
          <div>
            {test.jewelry_type === "earring"
              ? `Ear side: ${test.ear_side}`
              : test.jewelry_type === "necklace"
                ? "Attachment: neck / chest"
                : `Side: ${test.ear_side}`}
          </div>
          <div>
            Body point:{" "}
            {test.jewelry_type === "earring"
              ? "earlobe"
              : test.jewelry_type === "necklace"
                ? "neck"
                : test.jewelry_type === "ring"
                  ? "finger"
                  : "wrist"}
          </div>
          <div>
            Pass / fail: {test.pass_threshold} / {test.fail_threshold}
          </div>
        </dl>
      ) : null}
      {report ? (
        <>
          <ResultSummary report={report} />
          <PlacementResult
            frames={report.frames}
            activeId={active?.frame_id}
            activeSide={active?.side}
            onSelect={setActive}
          />
          <FrameViewer
            frame={active}
            passThreshold={report.thresholds.pass_threshold}
            failThreshold={report.thresholds.fail_threshold}
            zoneYScale={report.thresholds.zone_y_scale || 1}
          />
          <a className="text-sm underline" href={api.reportUrl(params.id)}>
            Download report
          </a>
        </>
      ) : (
        <p className="text-sm text-zinc-500">This test has no completed results yet.</p>
      )}
    </div>
  );
}
