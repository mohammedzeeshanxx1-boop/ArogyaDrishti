import { useState } from "react";
import type { AlertEvent } from "../api";
import { Empty, LevelBadge, VITAL_META, fmtDateTime } from "./ui";
import { LEVEL_MESSAGE } from "./risk";

const ACCENT: Record<AlertEvent["level"], string> = {
  URGENT: "border-red-600 bg-red-50/60", REVIEW: "border-orange-500 bg-orange-50/60", WATCH: "border-amber-400 bg-amber-50/50", NORMAL: "border-teal-500 bg-teal-50/40",
};
const KIND: Record<AlertEvent["kind"], string> = { raised: "Raised", escalated: "Escalated", "de-escalated": "De-escalated", resolved: "Resolved" };

export function AlertList({ alerts, names, showPatient = false, compact = false, limit, onAcknowledge }: {
  alerts: AlertEvent[] | null; names?: Record<string, string>; showPatient?: boolean; compact?: boolean; limit?: number;
  onAcknowledge?: (id: number) => Promise<void>;
}) {
  const [acking, setAcking] = useState<number | null>(null);
  const [ackError, setAckError] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  if (alerts === null) return <p className="text-sm text-navy-500">Loading alerts…</p>;
  if (alerts.length === 0) return <Empty>No alerts recorded. Alerts are created when an assessed risk level changes.</Empty>;
  const shown = limit && !all ? alerts.slice(0, limit) : alerts;
  return (
    <>
    <ul className={compact ? "divide-y divide-slate-100" : ""} data-testid="alert-list">
      {shown.map((a) => (
        <li key={a.id} className={compact ? "py-2.5" : `my-2 rounded-xl border-l-4 py-3 pl-4 pr-3 ${ACCENT[a.level]}`} title={a.observation ? `Source: ${a.observation}` : undefined} data-level={a.level}>
          <div className="flex flex-wrap items-center gap-2">
            <LevelBadge level={a.level} />
            <span className="text-xs font-semibold text-navy-700">{KIND[a.kind]}{a.previous_level ? ` from ${a.previous_level}` : ""}</span>
            {showPatient && <a className="text-sm font-semibold text-teal-700 hover:underline" href={`#/doctor/patients/${encodeURIComponent(a.patient_id)}`}>{a.patientName ?? names?.[a.patient_id] ?? "Patient"}</a>}
            <span className="ml-auto text-xs text-navy-500">{fmtDateTime(a.measured_at ?? a.created_at)}</span>
          </div>
          {!compact && a.level !== "NORMAL" && <p className="mt-1.5 text-sm font-semibold text-navy-900" data-testid="alert-message">{LEVEL_MESSAGE[a.level]}</p>}
          {!compact && <p className="mt-1 text-sm text-navy-700">{a.summary ?? a.reason}</p>}
          {!compact && !a.vital && /^NEWS2-style partial aggregate/.test(a.reason ?? "") ? (
            <div className="mt-1.5 min-w-0 rounded-lg bg-white/70 px-3 py-2 text-xs text-navy-700 ring-1 ring-slate-200" data-testid="alert-news2">
              <p className="font-semibold text-navy-900">NEWS2-style score {a.value} (partial)</p>
              <p className="mt-0.5">Parameters: SpO₂ (Oxygen Saturation), Heart Rate, Respiratory Rate, Body Temperature (up to 4 of the 7 NEWS2 parameters).
                {/a single parameter scores 3/.test(a.reason) ? " A single parameter scored 3." : ""}</p>
              <p className="mt-0.5">Classification: 0 → NORMAL · 1–4 → WATCH · 5–6 or any single parameter 3 → REVIEW · 7 or higher → URGENT</p>
              <p className="mt-0.5 text-navy-500">Per-parameter readings and scores are not stored with this alert; the patient's Risk assessment shows the current breakdown.</p>
            </div>
          ) : !compact && a.summary && a.reason && a.summary !== a.reason && <p className="mt-0.5 text-xs text-navy-500">Rule: {a.reason}{a.rule ? ` (${a.rule})` : ""}</p>}
          {!compact && (a.acknowledgements?.length || onAcknowledge) ? (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs">
              {(a.acknowledgements ?? []).map((k) => (
                <span key={k.username} className="rounded-full bg-teal-50 px-2 py-0.5 font-medium text-teal-800" data-testid="ack-badge">Acknowledged by {k.username} · {fmtDateTime(k.acknowledgedAt)}</span>
              ))}
              {onAcknowledge && !a.acknowledgedByMe && (
                <button type="button" disabled={acking !== null} data-testid="ack-button"
                  onClick={async () => { setAcking(a.id); setAckError(null); try { await onAcknowledge(a.id); } catch (e: any) { setAckError(String(e?.message ?? e)); } finally { setAcking(null); } }}
                  className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 font-semibold text-navy-900 hover:bg-slate-50 disabled:opacity-50">
                  {acking === a.id ? "Acknowledging…" : "Acknowledge"}</button>
              )}
            </div>
          ) : null}
          {!compact && a.vital && a.value !== null && (
            <p className="mt-0.5 text-xs text-navy-700">Triggering reading: <strong>{VITAL_META[a.vital]?.label ?? a.vital} {Number(a.value).toFixed(VITAL_META[a.vital]?.decimals ?? 1)} {VITAL_META[a.vital]?.unit ?? a.unit ?? ""}</strong></p>
          )}
        </li>
      ))}
    </ul>
    {ackError && <p role="alert" className="mt-2 text-xs text-red-700">Could not acknowledge: {ackError}</p>}
    {limit && alerts.length > limit && (
      <button type="button" onClick={() => setAll(!all)} className="mt-2 text-sm font-semibold text-teal-700 hover:underline">
        {all ? "Show fewer" : `Show all ${alerts.length} alerts`}
      </button>
    )}
    </>
  );
}
