"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const GROUPS = [
  {
    title: "Try-On QA",
    links: [
      { href: "/", label: "Dashboard" },
      { href: "/applications", label: "Applications" },
      { href: "/tests", label: "Test Configurations" },
      { href: "/tests/runs", label: "Test Runs" },
      { href: "/results", label: "Latest Results" },
      { href: "/reports", label: "Reports" },
      { href: "/settings", label: "Settings", icon: "gear" as const },
    ],
  },
  {
    title: "Agentic QA",
    links: [
      { href: "/agentic", label: "Bench" },
      { href: "/agentic/contracts", label: "Contracts" },
      { href: "/agentic/scenarios", label: "Scenarios" },
      { href: "/agentic/runs", label: "Runs" },
    ],
  },
];

function GearIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="mr-1.5 inline h-3.5 w-3.5 shrink-0 opacity-80"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
      />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  if (href === "/tests") {
    return pathname === "/tests" || (pathname.startsWith("/tests/") && !pathname.startsWith("/tests/runs"));
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const inAgentic = pathname.startsWith("/agentic");

  return (
    <div className="flex min-h-screen">
      <aside className="w-60 shrink-0 border-r border-[var(--border)] bg-[var(--sidebar)] px-4 py-6">
        <div className="px-2">
          <p className="text-xs uppercase tracking-[0.2em] text-[var(--muted)]">AIJewel QA</p>
          <h1 className="mt-1 text-lg font-semibold text-[var(--text)]">Unified Console</h1>
          <p className="mt-1 text-xs text-[var(--muted)]">
            {inAgentic ? "Agentic API testing" : "Virtual try-on testing"}
          </p>
        </div>
        <nav className="mt-8 space-y-6">
          {GROUPS.map((group) => (
            <div key={group.title}>
              <p className="mb-2 px-3 text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">{group.title}</p>
              <div className="space-y-1">
                {group.links.map((link) => {
                  const active = isActive(pathname, link.href);
                  return (
                    <Link
                      key={link.href}
                      href={link.href}
                      className={`block rounded px-3 py-2 text-sm ${
                        active
                          ? "bg-[var(--nav-active)] text-[var(--text)]"
                          : "text-[var(--muted)] hover:bg-[var(--nav-hover)] hover:text-[var(--text)]"
                      }`}
                    >
                      {"icon" in link && link.icon === "gear" ? <GearIcon /> : null}
                      {link.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </aside>
      <main className="flex-1 px-4 py-6 sm:px-8">{children}</main>
    </div>
  );
}

export function Card({ title, children, step }: { title?: string; children: ReactNode; step?: string }) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-5">
      {title ? (
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-[var(--card-title)]">
          {step ? <span className="mr-2 text-[var(--muted)]">{step}</span> : null}
          {title}
        </h2>
      ) : null}
      {children}
    </section>
  );
}

export function Field({ label, children }: { children: ReactNode; label: string }) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="text-[var(--muted)]">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "w-full rounded border border-[var(--border-strong)] bg-[var(--input)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--focus)]";
