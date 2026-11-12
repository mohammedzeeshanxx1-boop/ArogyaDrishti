import { useState } from "react";
import type { AlertEvent } from "../api";
import { Empty, LevelBadge, VITAL_META, fmtDateTime } from "./ui";

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
    <ul className="divide-y divide-slate-100" data-testid="alert-list">
      {shown.map((a) => (
        <li key={a.id} className={compact ? "py-2.5" : "py-3"} title={a.observation ? `Source: ${a.observation}` : undefined}>
          <div className="flex flex-wrap items-center gap-2">
            <LevelBadge level={a.level} />
            <span className="text-xs font-semibold text-navy-700">{KIND[a.kind]}{a.previous_level ? ` from ${a.previous_level}` : ""}</span>
            {showPatient && <a className="text-sm font-semibold text-teal-700 hover:underline" href={`#/doctor/patients/${encodeURIComponent(a.patient_id)}`}>{a.patientName ?? names?.[a.patient_id] ?? "Patient"}</a>}
            <span className="ml-auto text-xs text-navy-500">{fmtDateTime(a.measured_at ?? a.created_at)}</span>
          </div>
          {!compact && <p className="mt-1 text-sm text-navy-900">{a.reason}</p>}
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
            <p className="mt-0.5 text-xs text-navy-500">{VITAL_META[a.vital]?.label ?? a.vital}: {Number(a.value).toFixed(VITAL_META[a.vital]?.decimals ?? 1)} {VITAL_META[a.vital]?.unit ?? a.unit ?? ""}</p>
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
