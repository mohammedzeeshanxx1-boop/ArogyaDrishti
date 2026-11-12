import { useState, type ReactNode } from "react";
import type { StatusResponse, User } from "../api";
import { BRAND } from "../brand";
import { IconEye, IconLogout, IconMenu, IconX } from "./icons";

export interface NavItem { href: string; label: string; icon: (p: any) => ReactNode; match: (hash: string) => boolean }

function Brand() {
  return (
    <a href="#/" className="flex items-center gap-2.5 px-1">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-teal-600 text-white shadow-sm"><IconEye width={20} height={20} /></span>
      <span className="leading-tight">
        <span className="block text-[15px] font-bold tracking-wide text-white">AROGYA DRISHTI</span>
        <span className="block text-[11px] text-slate-300">Post-discharge monitoring</span>
      </span>
    </a>
  );
}

function ServiceDot({ ok, label }: { ok: boolean | null; label: string }) {
  return (
    <span className="flex items-center gap-2 text-xs text-slate-300">
      <span className={`h-2 w-2 rounded-full ${ok === null ? "bg-slate-500" : ok ? "bg-emerald-400" : "bg-red-400"}`} aria-hidden />
      {label}: <span className="text-slate-100">{ok === null ? "checking" : ok ? "connected" : "unreachable"}</span>
    </span>
  );
}

export function Shell({ user, nav, hash, title, subtitle, status, onSignOut, children, portal, headerRight }: {
  user: User; nav: NavItem[]; hash: string; title: string; subtitle?: ReactNode; status: StatusResponse | "down" | null;
  onSignOut: () => void; children: ReactNode; portal: "Doctor Portal" | "Patient Portal"; headerRight?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const api = status === null ? null : status !== "down" && status.services.api.status === "ok";
  const fhir = status === null ? null : status !== "down" && status.services.fhir.status === "ok";
  const sidebar = (
    <div className="flex h-full flex-col gap-6 bg-navy-900 px-4 py-5">
      <Brand />
      <div className="rounded-lg bg-white/5 px-3 py-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-teal-300">{portal}</p>
        <p className="truncate text-sm font-medium text-white" data-testid="signed-in-user">{user.displayName}</p>
        <p className="truncate text-xs text-slate-400">{user.username}</p>
      </div>
      <nav aria-label={portal} className="flex flex-col gap-1">
        {nav.map((n) => {
          const active = n.match(hash);
          const Icon = n.icon;
          return (
            <a key={n.href} href={n.href} onClick={() => setOpen(false)} aria-current={active ? "page" : undefined}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${active ? "bg-teal-600 text-white shadow-sm" : "text-slate-300 hover:bg-white/10 hover:text-white"}`}>
              <Icon /> {n.label}
            </a>
          );
        })}
      </nav>
      <div className="mt-auto space-y-3">
        <div className="space-y-1.5 rounded-lg bg-white/5 px-3 py-2.5" data-testid="service-status">
          <ServiceDot ok={api} label="Backend" />
          <ServiceDot ok={fhir} label="FHIR server" />
        </div>
        <button type="button" onClick={onSignOut} data-testid="sign-out"
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-300 hover:bg-white/10 hover:text-white">
          <IconLogout /> Sign out
        </button>
      </div>
    </div>
  );
  return (
    <div className="min-h-screen bg-surface font-sans text-navy-900 lg:pl-64">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button type="button" className="absolute inset-0 bg-navy-900/50" aria-label="Close navigation" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-72 shadow-xl">{sidebar}</div>
        </div>
      )}
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="flex items-center gap-3 px-4 py-3 sm:px-8">
          <button type="button" className="rounded-lg p-2 text-navy-700 hover:bg-slate-100 lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}>
            {open ? <IconX /> : <IconMenu />}
          </button>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-navy-900 sm:text-xl" data-testid="page-title">{title}</h1>
            {subtitle && <div className="truncate text-xs text-navy-500 sm:text-sm">{subtitle}</div>}
          </div>
          <div className="ml-auto flex items-center gap-3">
            {api === false && <span className="rounded-full bg-red-50 px-3 py-1 text-xs font-semibold text-red-700" role="status">Backend disconnected</span>}
            {headerRight}
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-8">{children}</main>
      <footer className="border-t border-slate-200 px-4 py-4 text-xs text-navy-500 sm:px-8">
        {BRAND.name} prototype · {BRAND.disclaimer} Not a medical device; not clinically validated. Patient records are synthetic (Synthea); vital signs are simulated unless a source states otherwise.
      </footer>
    </div>
  );
}
