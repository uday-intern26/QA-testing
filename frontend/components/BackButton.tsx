"use client";

import { useRouter } from "next/navigation";

export function BackButton({
  label = "Back",
  disabled = false,
}: {
  fallbackHref?: string;
  label?: string;
  disabled?: boolean;
}) {
  const router = useRouter();

  function goBack() {
    if (disabled) return;
    router.back();
  }

  return (
    <button
      type="button"
      onClick={goBack}
      disabled={disabled}
      aria-label={label}
      title={disabled ? "Back is available after a test is running or completed" : label}
      className="inline-flex items-center gap-2 rounded border border-zinc-700 bg-zinc-950 px-2.5 py-1.5 text-sm text-zinc-200 hover:border-zinc-500 hover:bg-zinc-900 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-zinc-700 disabled:hover:bg-zinc-950"
    >
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="h-4 w-4 shrink-0"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M15 18l-6-6 6-6" />
        <path d="M9 12h12" />
      </svg>
      <span>{label}</span>
    </button>
  );
}
