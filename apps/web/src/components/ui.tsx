import type { ReactNode } from "react";
import type { MonitoringStatus, RiskLevel } from "../api";

export const LEVEL_STYLE: Record<RiskLevel, string> = {
  NORMAL: "bg-teal-50 text-teal-800 ring-teal-600/30",
  WATCH: "bg-amber-50 text-amber-900 ring-amber-500/40",
  REVIEW: "bg-orange-50 text-orange-900 ring-orange-600/40",
  URGENT: "bg-red-600 text-white ring-red-700",
};
export const LEVEL_DOT: Record<RiskLevel, string> = { NORMAL: "bg-teal-600", WATCH: "bg-amber-500", REVIEW: "bg-orange-600", URGENT: "bg-red-600" };
export const LEVEL_RANK: Record<RiskLevel, number> = { NORMAL: 0, WATCH: 1, REVIEW: 2, URGENT: 3 };

export function LevelBadge({ level, large = false }: { level: RiskLevel | null; large?: boolean }) {
  const size = large ? "px-3 py-1.5 text-base" : "px-2 py-0.5 text-xs";
  if (!level) return <span className={`inline-flex items-center rounded-md bg-slate-100 font-semibold text-slate-600 ring-1 ring-inset ring-slate-300 ${size}`}>Not assessed</span>;
  return <span className={`inline-flex items-center gap-1.5 rounded-md font-semibold ring-1 ring-inset ${LEVEL_STYLE[level]} ${size}`}>
    <span className={`h-2 w-2 rounded-full ${level === "URGENT" ? "bg-white" : LEVEL_DOT[level]}`} aria-hidden />{level}
  </span>;
}

const MON_TEXT: Record<MonitoringStatus, [string, string]> = {
  active: ["Receiving data", "bg-teal-600"],
  stale: ["Data stale", "bg-amber-500"],
  no_recent_data: ["No recent data", "bg-slate-400"],
  unavailable: ["Unavailable", "bg-red-500"],
};
export function MonitoringBadge({ status }: { status: MonitoringStatus }) {
  const [text, dot] = MON_TEXT[status];
  return <span className="inline-flex items-center gap-1.5 text-xs font-medium text-navy-700"><span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />{text}</span>;
}

export function Card({ title, children, right, className = "" }: { title?: string; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <section className={`min-w-0 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="text-base font-semibold text-navy-900">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-navy-500">{children}</p>;
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">{children}</p>;
}

export const displayName = (n?: string) => (n ?? "").replace(/\d+/g, "").replace(/\s+/g, " ").trim();
export const fmtTime = (iso?: string | null) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
export const fmtDate = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" }) : "—");
export const fmtDateTime = (iso?: string | null) => (iso ? `${fmtDate(iso)} ${fmtTime(iso)}` : "—");
export const ago = (iso?: string | null) => {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
};
export const tidyCondition = (s?: string) => (s ?? "").replace(/\s*\((disorder|finding|situation|procedure)\)$/i, "");

// Display units (the stored FHIR values use UCUM: /min, %, Cel).
export const VITAL_META: Record<string, { label: string; short: string; unit: string; decimals: number; step: number }> = {
  heart_rate: { label: "Heart rate", short: "Heart rate", unit: "bpm", decimals: 0, step: 3 },
  spo2: { label: "Oxygen saturation (SpO₂)", short: "SpO₂", unit: "%", decimals: 0, step: 1 },
  respiratory_rate: { label: "Respiratory rate", short: "Respiratory rate", unit: "breaths/min", decimals: 0, step: 2 },
  body_temperature: { label: "Body temperature", short: "Temperature", unit: "°C", decimals: 1, step: 0.2 },
};
