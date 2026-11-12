import type { AlertEvent } from "../api";
import { Empty, LevelBadge, VITAL_META, fmtDateTime } from "./ui";

const KIND: Record<AlertEvent["kind"], string> = { raised: "Raised", escalated: "Escalated", "de-escalated": "De-escalated", resolved: "Resolved" };

export function AlertList({ alerts, names, showPatient = false }: { alerts: AlertEvent[] | null; names?: Record<string, string>; showPatient?: boolean }) {
  if (alerts === null) return <p className="text-sm text-navy-500">Loading alerts…</p>;
  if (alerts.length === 0) return <Empty>No alerts recorded. Alerts are created when an assessed risk level changes.</Empty>;
  return (
    <ul className="divide-y divide-slate-100" data-testid="alert-list">
      {alerts.map((a) => (
        <li key={a.id} className="py-3">
          <div className="flex flex-wrap items-center gap-2">
            <LevelBadge level={a.level} />
            <span className="text-xs font-semibold text-navy-700">{KIND[a.kind]}{a.previous_level ? ` from ${a.previous_level}` : ""}</span>
            {showPatient && <a className="text-sm font-semibold text-teal-700 hover:underline" href={`#/patient/${encodeURIComponent(a.patient_id)}`}>{names?.[a.patient_id] ?? "Patient"}</a>}
            <span className="ml-auto text-xs text-navy-500">{fmtDateTime(a.measured_at ?? a.created_at)}</span>
          </div>
          <p className="mt-1 text-sm text-navy-900">{a.reason}</p>
          <p className="mt-0.5 text-xs text-navy-500">
            {a.vital && a.value !== null ? `${VITAL_META[a.vital]?.label ?? a.vital}: ${a.value} ${a.unit ?? ""} · ` : ""}
            {a.observation ? <>Source: <span className="font-mono">{a.observation}</span></> : null}
          </p>
        </li>
      ))}
    </ul>
  );
}
