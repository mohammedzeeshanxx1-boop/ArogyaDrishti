import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  clearScale2, fetchAlerts, fetchMonitoringStatus, fetchOverview, setScale2,
  type AlertEvent, type MonitoringSourceStatus, type Overview, type OverviewPatient, type RiskLevel, type Scale2Status,
} from "../api";
import { AlertList } from "../components/AlertList";
import { acknowledgeAlert, exportUrls } from "../api";
import { IconDownload } from "../components/icons";
import { useNotifications } from "../notifications";
import { VideoLink } from "./data";
import { LabPromo } from "./lab";
import { IconChevron, IconSearch } from "../components/icons";
import { RiskPanel } from "../components/risk";
import { SimulationPanel } from "../components/SimulationPanel";
import { ORDER, VitalCard, VitalCharts } from "../components/vitals";
import { Card, Empty, ErrorNote, LEVEL_RANK, LevelBadge, MonitoringBadge, ago, displayName, fmtDate, fmtDateTime, fmtTime, tidyCondition } from "../components/ui";
import { useMonitor, useProfile } from "../monitor";

export const patientHref = (id: string) => `#/doctor/patients/${encodeURIComponent(id)}`;

/** Overview of all patients from GET /api/clinical/overview (polled). */
export function useOverview(intervalMs = 8000) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => fetchOverview().then((d) => { if (alive) { setData(d); setError(null); } }).catch((e) => alive && setError(String(e?.message ?? e)));
    void load();
    const t = window.setInterval(load, intervalMs);
    return () => { alive = false; window.clearInterval(t); };
  }, [intervalMs]);
  return { data, error };
}

const levelOf = (p: OverviewPatient) => (p.monitoring.assessable ? p.monitoring.level : null);

function Stat({ label, value, hint, tone = "navy", testid }: { label: string; value: ReactNode; hint?: string; tone?: "navy" | "teal" | "amber" | "orange" | "red"; testid: string }) {
  const bar = { navy: "bg-navy-700", teal: "bg-teal-600", amber: "bg-amber-500", orange: "bg-orange-600", red: "bg-red-600" }[tone];
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" data-testid={testid}>
      <span className={`absolute inset-y-0 left-0 w-1 ${bar}`} aria-hidden />
      <p className="text-sm font-medium text-navy-500">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums text-navy-900" data-testid={`${testid}-value`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-navy-500">{hint}</p>}
    </div>
  );
}

export function DoctorDashboard() {
  const { data, error } = useOverview();
  const [alerts, setAlerts] = useState<AlertEvent[] | null>(null);
  const [source, setSource] = useState<MonitoringSourceStatus | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => {
      fetchAlerts(undefined, 6).then((a) => alive && setAlerts(a.alerts)).catch(() => alive && setAlerts([]));
      fetchMonitoringStatus().then((s) => alive && setSource(s)).catch(() => alive && setSource(null));
    };
    load();
    const t = window.setInterval(load, 8000);
    return () => { alive = false; window.clearInterval(t); };
  }, []);
  const pts = data?.patients ?? [];
  const count = (l: RiskLevel) => pts.filter((p) => levelOf(p) === l).length;
  const names = Object.fromEntries(pts.map((p) => [p.id, displayName(p.name)]));
  const attention = [...pts].filter((p) => levelOf(p) && levelOf(p) !== "NORMAL")
    .sort((a, b) => LEVEL_RANK[levelOf(b)!] - LEVEL_RANK[levelOf(a)!]);
  const v = (n: number) => (data ? n : "—");
  return (
    <div className="space-y-6">
      {error && <ErrorNote>Could not load the patient overview: {error}</ErrorNote>}
      <LabPromo />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat testid="stat-total" label="Patients" value={v(pts.length)} hint="Discharged patients in the FHIR server" />
        <Stat testid="stat-monitored" tone="teal" label="With current monitoring data" value={v(pts.filter((p) => p.monitoring.monitoringStatus === "active").length)}
          hint={`Readings in the last ${data?.staleAfterMinutes ?? 15} min`} />
        <Stat testid="stat-review" tone="orange" label="Require review" value={v(count("REVIEW"))} hint={`${v(count("WATCH"))} more on watch`} />
        <Stat testid="stat-urgent" tone="red" label="Urgent" value={v(count("URGENT"))} hint="Flagged for urgent clinical review" />
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card title="Needs attention" right={<a href="#/doctor/patients" className="text-sm font-semibold text-teal-700 hover:underline">All patients</a>}>
          {!data ? <p className="text-sm text-navy-500">Loading…</p> : attention.length === 0 ? (
            <Empty>No patient currently has a WATCH, REVIEW or URGENT assessment. Patients without recent readings are listed as not assessed in the directory.</Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {attention.map((p) => (
                <li key={p.id}>
                  <a href={patientHref(p.id)} className="flex items-center gap-3 py-3 hover:bg-slate-50" data-testid="attention-row">
                    <LevelBadge level={levelOf(p)} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-navy-900">{displayName(p.name)}</span>
                      <span className="block truncate text-xs text-navy-500">{p.monitoring.topReason ?? "—"}</span>
                    </span>
                    <span className="hidden text-xs text-navy-500 sm:block">{ago(p.monitoring.lastObservationAt)}</span>
                    <IconChevron className="text-slate-400" />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="space-y-6">
          <Card title="Monitoring source">
            {source ? (
              <div className="space-y-1 text-sm text-navy-700" data-testid="source-status">
                <p className="font-medium text-navy-900">{source.status === "receiving" ? "Receiving readings" : source.status === "idle" ? "Idle: no readings in the last few minutes" : "No source has sent readings"}</p>
                {source.latestSourceLabel && <p>Latest source: {source.latestSourceLabel}</p>}
                {source.lastIngestionAt && <p className="text-xs text-navy-500">Last reading stored {ago(source.lastIngestionAt)} ({fmtDateTime(source.lastIngestionAt)})</p>}
                <p className="text-xs text-navy-500">Physical devices connected: {source.physicalDevicesConnected}</p>
              </div>
            ) : <p className="text-sm text-navy-500">Status unavailable.</p>}
          </Card>
          <Card title="Recent alerts" right={<a href="#/doctor/alerts" className="text-sm font-semibold text-teal-700 hover:underline">View all</a>}>
            <AlertList alerts={alerts} names={names} showPatient compact />
          </Card>
        </div>
      </div>
    </div>
  );
}

type Filter = "all" | RiskLevel | "none" | "active" | "no_data";
type Sort = "risk" | "name" | "recent";
const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" }, { id: "URGENT", label: "Urgent" }, { id: "REVIEW", label: "Review" }, { id: "WATCH", label: "Watch" },
  { id: "NORMAL", label: "Normal" }, { id: "none", label: "Not assessed" }, { id: "active", label: "Receiving data" }, { id: "no_data", label: "No recent data" },
];

export function PatientDirectory() {
  const { data, error } = useOverview();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("risk");
  const rows = useMemo(() => {
    const list = (data?.patients ?? []).filter((p) => {
      if (q && !displayName(p.name).toLowerCase().includes(q.trim().toLowerCase())) return false;
      const lv = levelOf(p);
      if (filter === "all") return true;
      if (filter === "none") return lv === null;
      if (filter === "active") return p.monitoring.monitoringStatus === "active";
      if (filter === "no_data") return p.monitoring.monitoringStatus === "no_recent_data";
      return lv === filter;
    });
    const t = (p: OverviewPatient) => (p.monitoring.lastObservationAt ? Date.parse(p.monitoring.lastObservationAt) : 0);
    return list.sort((a, b) =>
      sort === "name" ? displayName(a.name).localeCompare(displayName(b.name))
        : sort === "recent" ? t(b) - t(a)
          : (levelOf(b) ? LEVEL_RANK[levelOf(b)!] : -1) - (levelOf(a) ? LEVEL_RANK[levelOf(a)!] : -1) || t(b) - t(a));
  }, [data, q, filter, sort]);
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm lg:flex-row lg:items-center">
        <label className="relative flex-1">
          <span className="sr-only">Search patients by name</span>
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" width={18} height={18} />
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search patients by name" data-testid="search"
            className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-10 pr-3 text-sm placeholder:text-slate-400" />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm text-navy-700">Status{" "}
            <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} data-testid="filter" className="ml-1 rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm">
              {FILTERS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </label>
          <label className="text-sm text-navy-700">Sort{" "}
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} data-testid="sort" className="ml-1 rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm">
              <option value="risk">Risk (highest first)</option><option value="name">Name</option><option value="recent">Most recent observation</option>
            </select>
          </label>
        </div>
      </div>
      {error && <ErrorNote>Could not load patients: {error}</ErrorNote>}
      {!data && !error && <p className="text-sm text-navy-500">Loading patients…</p>}
      {data && (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-3">
            <p className="text-xs text-navy-500" data-testid="result-count">{rows.length} of {data.patients.length} patients</p>
            <div className="flex gap-3 text-sm font-semibold">
              <a href="#/doctor/data" className="text-teal-700 hover:underline">+ Add patient</a>
              <a href={exportUrls.directory} download className="inline-flex items-center gap-1 text-teal-700 hover:underline"><IconDownload width={16} height={16} />Export CSV</a>
            </div>
          </div>
          {rows.length === 0 ? <div className="p-5"><Empty>No patients match this search and filter.</Empty></div> : (
            <>
              <table className="hidden w-full text-left text-sm md:table" data-testid="patient-table">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-navy-500">
                  <tr><th className="px-5 py-3 font-semibold">Patient</th><th className="px-3 py-3 font-semibold">Age</th><th className="px-3 py-3 font-semibold">Discharged</th>
                    <th className="px-3 py-3 font-semibold">Status</th><th className="px-3 py-3 font-semibold">Monitoring</th><th className="px-3 py-3 font-semibold">Last updated</th><th /></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {rows.map((p) => (
                    <tr key={p.id} className="cursor-pointer hover:bg-teal-50/40" onClick={() => { window.location.hash = patientHref(p.id); }} data-testid="patient-row">
                      <td className="px-5 py-3"><a href={patientHref(p.id)} className="font-medium text-navy-900 hover:text-teal-700" onClick={(e) => e.stopPropagation()}>{displayName(p.name)}</a>
                        <span className="block text-xs capitalize text-navy-500">{p.gender ?? ""}</span></td>
                      <td className="px-3 py-3 tabular-nums">{p.age ?? "—"}</td>
                      <td className="px-3 py-3">{fmtDate(p.lastDischarge)}</td>
                      <td className="px-3 py-3"><LevelBadge level={levelOf(p)} /></td>
                      <td className="px-3 py-3"><MonitoringBadge status={p.monitoring.monitoringStatus} /></td>
                      <td className="px-3 py-3 text-navy-700" title={fmtDateTime(p.monitoring.lastObservationAt)}>{p.monitoring.lastObservationAt ? ago(p.monitoring.lastObservationAt) : "—"}</td>
                      <td className="pr-4"><IconChevron className="text-slate-400" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul className="divide-y divide-slate-100 md:hidden">
                {rows.map((p) => (
                  <li key={p.id}>
                    <a href={patientHref(p.id)} className="flex items-center gap-3 px-4 py-3" data-testid="patient-card">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-navy-900">{displayName(p.name)}</span>
                        <span className="block text-xs text-navy-500">{p.age ?? "—"} y · discharged {fmtDate(p.lastDischarge)} · {p.monitoring.lastObservationAt ? ago(p.monitoring.lastObservationAt) : "no readings"}</span>
                      </span>
                      <LevelBadge level={levelOf(p)} />
                    </a>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Scale2Panel({ pid, status, onChange }: { pid: string; status: Scale2Status | undefined; onChange: () => void }) {
  const [by, setBy] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await fn(); setBy(""); setReason(""); onChange(); } catch (e: any) { setErr(String(e?.message ?? e)); } finally { setBusy(false); }
  };
  return (
    <Card title="Clinical configuration: SpO₂ scale">
      <p className="text-sm text-navy-700">Current: <strong>Scale {status?.scale ?? 1}</strong>{status?.flag ? "" : " (default)"}</p>
      <p className="mt-1 text-xs text-navy-500">Scale 2 is for patients with a clinician-prescribed SpO₂ target of 88–92 %. It requires an attributed clinician decision and is never inferred from a diagnosis.</p>
      {status?.flag ? (
        <div className="mt-3 rounded-xl bg-slate-50 p-3 text-sm">
          <p className="text-navy-900">Scale 2 recorded by <strong>{status.flag.author}</strong> on {fmtDateTime(status.flag.since)}</p>
          <p className="text-xs text-navy-700">{status.flag.reason}</p>
          <button type="button" disabled={busy} onClick={() => run(() => clearScale2(pid))}
            className="mt-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-navy-900 hover:bg-slate-50 disabled:opacity-50">Return to Scale 1</button>
        </div>
      ) : (
        <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); void run(() => setScale2(pid, by.trim(), reason.trim())); }}>
          <label className="text-xs font-medium text-navy-700">Clinician name
            <input value={by} onChange={(e) => setBy(e.target.value)} required minLength={2} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="text-xs font-medium text-navy-700">Clinical reason
            <input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={5} placeholder="e.g. hypercapnic respiratory failure, target 88–92 %"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <button type="submit" disabled={busy || by.trim().length < 2 || reason.trim().length < 5}
            className="justify-self-start rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-40">Record Scale 2 decision</button>
        </form>
      )}
      {status?.supportingConditions?.length ? <p className="mt-2 text-xs text-navy-500">Related conditions on record: {status.supportingConditions.map(tidyCondition).join(", ")}</p> : null}
      {err && <div className="mt-2"><ErrorNote>{err}</ErrorNote></div>}
    </Card>
  );
}

export function PatientSummary({ pid, compact = false }: { pid: string; compact?: boolean }) {
  const { profile, error } = useProfile(pid);
  if (error) return <ErrorNote>Could not load the patient record: {error}</ErrorNote>;
  if (!profile) return <Card><p className="text-sm text-navy-500">Loading patient record…</p></Card>;
  const conditions = [...profile.activeConditions].sort((a, b) => Number(!/\(disorder\)/.test(a.condition ?? "")) - Number(!/\(disorder\)/.test(b.condition ?? "")));
  const lim = compact ? 6 : 50;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold text-navy-900" data-testid="patient-name">{displayName(profile.patient.name)}</h2>
          <p className="text-sm capitalize text-navy-500">{profile.patient.age} years · {profile.patient.gender} · born {fmtDate(profile.patient.birthDate)} · <span className="normal-case">{(profile.patient as any).source === "synthea" || (profile.patient as any).source === undefined ? "synthetic record (Synthea)" : "registered in the Doctor Portal (test record)"}</span></p>
        </div>
        {profile.discharge && (
          <div className="rounded-xl bg-teal-50 px-4 py-2 text-sm text-navy-900">
            <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">Discharged</p>
            <p className="font-medium">{fmtDate(profile.discharge.discharged)}</p>
            {profile.discharge.facility && <p className="text-xs capitalize text-navy-700">{profile.discharge.facility.toLowerCase()}</p>}
          </div>
        )}
      </div>
      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-navy-500">Active conditions ({conditions.length})</h3>
          <ul className="mt-2 space-y-1 text-sm text-navy-900" data-testid="conditions">
            {conditions.slice(0, lim).map((c) => <li key={c.id} className={/\(disorder\)/.test(c.condition ?? "") ? "" : "text-navy-500"}>{tidyCondition(c.condition)}</li>)}
            {conditions.length > lim && <li className="text-navy-500">+ {conditions.length - lim} more</li>}
          </ul>
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-navy-500">Active medications ({profile.activeMedications.length})</h3>
          <ul className="mt-2 space-y-1 text-sm text-navy-900" data-testid="medications">
            {profile.activeMedications.slice(0, lim).map((m) => <li key={m.id}>{m.medication}</li>)}
            {profile.activeMedications.length > lim && <li className="text-navy-500">+ {profile.activeMedications.length - lim} more</li>}
          </ul>
          {profile.allergies.length > 0 && <p className="mt-3 text-xs text-navy-700">Allergies: {profile.allergies.map((a) => a.substance).join(", ")}</p>}
        </div>
      </div>
    </section>
  );
}

export function PatientMonitor({ pid }: { pid: string }) {
  const { monitor, live, error, refresh, markView, pending, viewStart } = useMonitor(pid);
  const [alerts, setAlerts] = useState<AlertEvent[] | null>(null);
  const [tick, setTick] = useState(0);
  const simRunning = !!monitor?.simulator?.running;
  useEffect(() => {
    let alive = true;
    const load = () => fetchAlerts(pid, 50).then((a) => alive && setAlerts(a.alerts)).catch(() => alive && setAlerts([]));
    void load();
    const t = window.setInterval(load, simRunning ? 2000 : 10000);
    return () => { alive = false; window.clearInterval(t); };
  }, [pid, simRunning, tick]);
  const afterSim = useCallback(() => { void refresh(); setTick((n) => n + 1); }, [refresh]);
  const notif = useNotifications();
  const ack = useCallback(async (id: number) => { await (notif ? notif.acknowledge(id) : acknowledgeAlert(id).then(() => undefined)); setTick((n) => n + 1); }, [notif]);
  const noData = !!monitor && monitor.observationCount === 0;
  const waiting = pending || noData;
  const windowMin = monitor ? (Date.parse(monitor.evaluatedAt) - Date.parse(monitor.windowStart)) / 60000 : 0;
  const resetView = !!monitor && windowMin < monitor.assessment.recentWindowMinutes - 1;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <a href="#/doctor/patients" className="inline-flex items-center gap-1 text-sm font-medium text-teal-700 hover:underline">← Patient directory</a>
        <div className="flex flex-wrap items-center gap-2" data-testid="patient-actions">
          <a href={exportUrls.record(pid)} download className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-navy-900 hover:bg-slate-50"><IconDownload width={16} height={16} />Record CSV</a>
          <a href={exportUrls.observations(pid)} download className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-navy-900 hover:bg-slate-50"><IconDownload width={16} height={16} />Vitals CSV</a>
          <VideoLink label="Start Video Consultation" testid="video-patient-page" />
        </div>
      </div>
      <PatientSummary pid={pid} compact />

      <section aria-labelledby="demo-heading" className="rounded-2xl border border-dashed border-teal-600/50 bg-teal-50/40 p-1">
        <p id="demo-heading" className="px-4 pt-3 text-xs font-semibold uppercase tracking-wider text-teal-700">Demo / Simulation · simulated readings, not a real device</p>
        <SimulationPanel pid={pid} sim={monitor?.simulator} windowStart={viewStart} onNewView={markView} onChange={afterSim} />
      </section>

      <div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-navy-900">Latest vital signs{resetView || pending ? <span className="ml-2 text-sm font-normal text-navy-500">current run since {fmtTime(viewStart)}</span> : null}</h2>
          <span data-testid="live-mode" className="inline-flex items-center gap-1.5 text-xs text-navy-500">
            <span className={`h-2 w-2 rounded-full ${live === "websocket" ? "bg-emerald-500" : live === "polling" ? "bg-amber-500" : "bg-slate-400"}`} aria-hidden />
            {live === "websocket" ? "Live updates" : live === "polling" ? "Updating every few seconds (reconnecting)" : "Connecting…"}
            {monitor && <MonitoringBadge status={monitor.assessment.monitoringStatus} />}
          </span>
        </div>
        {error && !monitor && <ErrorNote>Monitoring data unavailable: {error}</ErrorNote>}
        {waiting && monitor && (
          <p className="mb-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-navy-700" data-testid="waiting">
            {pending ? "Waiting for readings from the new run…"
              : simRunning ? "Waiting for readings… the simulated source has started; the first readings appear within a few seconds."
                : resetView ? `Waiting for readings. The view was reset at ${fmtTime(monitor.windowStart)}; no readings have arrived since.`
                  : `No vital-sign readings in the last ${monitor.assessment.recentWindowMinutes} minutes. No monitoring source is currently sending data for this patient.`}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {ORDER.map((k) => <VitalCard key={k} k={k} monitor={monitor} waiting={waiting} clinician />)}
        </div>
      </div>

      <VitalCharts monitor={monitor} waiting={waiting} clinician />
      <RiskPanel monitor={monitor} waiting={waiting} />
      <Card title="Alert history" right={<span className="text-xs text-navy-500">Recorded when the assessed level changes</span>}><AlertList alerts={alerts} limit={8} onAcknowledge={ack} /></Card>
      <Scale2Panel pid={pid} status={monitor?.scale2} onChange={() => void refresh()} />
    </div>
  );
}

export function AlertsPage() {
  const { data } = useOverview(15000);
  const [alerts, setAlerts] = useState<AlertEvent[] | null>(null);
  const [tick, setTick] = useState(0);
  const notif = useNotifications();
  useEffect(() => {
    let alive = true;
    const load = () => fetchAlerts(undefined, 100).then((a) => alive && setAlerts(a.alerts)).catch(() => alive && setAlerts([]));
    void load();
    const t = window.setInterval(load, 8000);
    return () => { alive = false; window.clearInterval(t); };
  }, [tick]);
  const ack = async (id: number) => { await (notif ? notif.acknowledge(id) : acknowledgeAlert(id).then(() => undefined)); setTick((n) => n + 1); };
  const names = Object.fromEntries((data?.patients ?? []).map((p) => [p.id, displayName(p.name)]));
  return (
    <Card title="Alert history (all patients)" right={<span className="text-xs text-navy-500">Recorded when an assessed risk level changes. Acknowledging records your review; it never changes the alert.</span>}>
      <AlertList alerts={alerts} names={names} showPatient onAcknowledge={ack} />
    </Card>
  );
}

