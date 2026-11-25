"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

export default function RunRedirectPage() {
  const params = useParams<{ runId: string }>();
  const router = useRouter();
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .runs()
      .then((items) => {
        if (cancelled) return;
        const match = items.find((item) => item.test_run_id === params.runId);
        if (match?.test_id) {
          router.replace(`/tests/${encodeURIComponent(String(match.test_id))}`);
          return;
        }
        setMissing(true);
      })
      .catch(() => {
        if (!cancelled) setMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [params.runId, router]);

  if (missing) {
    return (
      <div className="space-y-2 text-sm text-zinc-400">
        <p>No results found for run {params.runId}.</p>
        <Link className="underline" href="/tests/runs">
          Back to test runs
        </Link>
      </div>
    );
  }

  return <p className="text-sm text-zinc-400">Opening results…</p>;
}
