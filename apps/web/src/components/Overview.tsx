import { useEffect, useMemo, useState } from "react";
import { fetchAlerts, fetchOverview, type AlertEvent, type Overview as OverviewData, type OverviewPatient, type RiskLevel } from "../api";
import { AlertList } from "./AlertList";
import { Card, Empty, ErrorNote, LEVEL_RANK, LevelBadge, MonitoringBadge, VITAL_META, ago, displayName, fmtDate } from "./ui";

type Filter = "ALL" | RiskLevel | "NOT_ASSESSED";
const FILTERS: [Filter, string][] = [["ALL", "All"], ["URGENT", "Urgent"], ["REVIEW", "Review"], ["WATCH", "Watch"], ["NORMAL", "Normal"], ["NOT_ASSESSED", "Not assessed"]];

function PatientCard({ p }: { p: OverviewPatient }) {
  const m = p.monitoring;
  return (
    <a href={`#/patient/${encodeURIComponent(p.id)}`} data-testid="patient-card"
      className="block min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-teal-400 hover:shadow focus-visible:border-teal-600">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-semibold text-navy-900">{displayName(p.name)}</p>
          <p className="text-xs text-navy-500">{p.age ?? "?"} y · {p.gender ?? "—"} · discharged {fmtDate(p.lastDischarge)}</p>
        </div>
        <LevelBadge level={m.assessable ? m.level : null} />
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <MonitoringBadge status={m.monitoringStatus} />
        <span className="text-xs text-navy-500">{m.lastObservationAt ? `Last reading ${ago(m.lastObservationAt)}` : "No readings in the last " + m.recentWindowMinutes + " min"}</span>
      </div>
      {Object.keys(m.latest).length > 0 ? (
        <dl className="mt-3 grid grid-cols-4 gap-1 text-center">
          {(["heart_rate", "spo2", "respiratory_rate", "body_temperature"] as const).map((k) => {
            const v = m.latest[k];
            const meta = VITAL_META[k];
            return (
              <div key={k} className="rounded-lg bg-slate-50 px-1 py-1.5">
                <dt className="text-[10px] uppercase text-navy-500">{k === "heart_rate" ? "HR" : k === "spo2" ? "SpO₂" : k === "respiratory_rate" ? "RR" : "Temp"}</dt>
                <dd className="text-sm font-semibold tabular-nums text-navy-900">{v ? v.value.toFixed(meta.decimals) : "—"}</dd>
              </div>
            );
          })}
        </dl>
      ) : null}
      {m.assessable && m.topReason && <p className="mt-2 line-clamp-2 text-xs text-navy-700">{m.topReason}</p>}
      {!m.assessable && m.monitoringStatus !== "no_recent_data" && (
        <p className="mt-2 text-xs text-navy-500">Not enough trusted readings to assess ({m.trustedVitals} of {m.requiredTrustedVitals} vitals).</p>
      )}
    </a>
  );
}

export function Overview({ onUpdate }: { onUpdate: () => void }) {
  const [data, setData] = useState<OverviewData | null>(null);
  const [alerts, setAlerts] = useState<AlertEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("ALL");

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [o, a] = await Promise.all([fetchOverview(), fetchAlerts(undefined, 20)]);
        if (!alive) return;
        setData(o); setAlerts(a.alerts); setError(null); onUpdate();
      } catch (e: any) {
        if (alive) setError(String(e?.message ?? e));
      }
    };
    void load();
    const t = window.setInterval(() => void load(), 10000);
    return () => { alive = false; window.clearInterval(t); };
  }, [onUpdate]);

  const names = useMemo(() => Object.fromEntries((data?.patients ?? []).map((p) => [p.id, displayName(p.name)])), [data]);
  const shown = useMemo(() => (data?.patients ?? [])
    .filter((p) => displayName(p.name).toLowerCase().includes(q.trim().toLowerCase()))
    .filter((p) => filter === "ALL" || (filter === "NOT_ASSESSED" ? !p.monitoring.assessable : p.monitoring.assessable && p.monitoring.level === filter))
    .sort((a, b) => (b.monitoring.assessable ? LEVEL_RANK[b.monitoring.level!] + 1 : 0) - (a.monitoring.assessable ? LEVEL_RANK[a.monitoring.level!] + 1 : 0)
      || displayName(a.name).localeCompare(displayName(b.name))), [data, q, filter]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const p of data?.patients ?? []) { const k = p.monitoring.assessable ? p.monitoring.level! : "NOT_ASSESSED"; c[k] = (c[k] ?? 0) + 1; }
    return c;
  }, [data]);

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-navy-900">Discharged patients</h2>
            <p className="text-sm text-navy-500">
              {data ? `${data.patients.length} patients · status from the last ${data.recentWindowMinutes} min of readings · stale after ${data.staleAfterMinutes} min` : "Loading…"}
            </p>
          </div>
          <label className="w-full sm:w-64">
            <span className="sr-only">Search patients</span>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" />
          </label>
        </div>
        <div role="group" aria-label="Filter by risk" className="flex flex-wrap gap-2">
          {FILTERS.map(([f, label]) => (
            <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}
              className={`rounded-full border px-3 py-1 text-xs font-semibold ${filter === f ? "border-navy-900 bg-navy-900 text-white" : "border-slate-300 bg-white text-navy-700 hover:bg-slate-50"}`}>
              {label}{f !== "ALL" && counts[f] ? ` (${counts[f]})` : ""}
            </button>
          ))}
        </div>
        {error && <ErrorNote>Could not load patients: {error}</ErrorNote>}
        {!data && !error && <p className="text-sm text-navy-500">Loading patients from the FHIR server…</p>}
        {data && data.patients.length === 0 && <Empty>No patient records are available from the FHIR server.</Empty>}
        {data && data.patients.length > 0 && shown.length === 0 && <Empty>No patients match this search or filter.</Empty>}
        <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
          {shown.map((p) => <PatientCard key={p.id} p={p} />)}
        </div>
      </div>
      <Card title="Recent alerts">
        <AlertList alerts={alerts} names={names} showPatient />
      </Card>
    </div>
  );
}
