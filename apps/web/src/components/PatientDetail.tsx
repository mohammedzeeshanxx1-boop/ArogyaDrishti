import { useCallback, useEffect, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  clearScale2, fetchAlerts, fetchMonitor, fetchProfile, monitorSocketUrl, setScale2,
  type AlertEvent, type Monitor, type PatientProfile, type Scale2Status, type VitalKey,
} from "../api";
import { AlertList } from "./AlertList";
import { SimulationPanel } from "./SimulationPanel";
import { Card, Empty, ErrorNote, LevelBadge, MonitoringBadge, VITAL_META, ago, displayName, fmtDate, fmtDateTime, fmtTime, tidyCondition } from "./ui";

const POLL_MS = 3000;
const ORDER: VitalKey[] = ["heart_rate", "spo2", "respiratory_rate", "body_temperature"];
const DOMAIN: Record<VitalKey, [number, number]> = { heart_rate: [40, 150], spo2: [80, 100], respiratory_rate: [6, 36], body_temperature: [35, 40] };

/** Live monitor data: WebSocket push, falling back to polling. */
function useMonitor(pid: string, onUpdate: () => void) {
  const [monitor, setMonitor] = useState<Monitor | null>(null);
  const [live, setLive] = useState<"connecting" | "websocket" | "polling">("connecting");
  const [error, setError] = useState<string | null>(null);
  const liveRef = useRef(live);
  liveRef.current = live;
  // After Start/Reset, frames built for the previous view (e.g. a WebSocket frame computed just before the click)
  // are dropped until the new view arrives. The guard expires, so a restarted API can never freeze the page.
  const guard = useRef<{ view: string; until: number }>({ view: "", until: 0 });
  const [pending, setPending] = useState<string | null>(null);
  const accept = useCallback((m: Monitor) => {
    const g = guard.current;
    if (Date.now() < g.until) {
      if (m.windowStart < g.view) return;
      guard.current = { view: "", until: 0 }; setPending(null);
    }
    setMonitor(m);
  }, []);
  const markView = useCallback((windowStart: string) => {
    guard.current = { view: windowStart, until: Date.now() + 8000 }; setPending(windowStart);
    window.setTimeout(() => { if (guard.current.view === windowStart) { guard.current = { view: "", until: 0 }; setPending(null); } }, 8000);
  }, []);

  const poll = useCallback(async () => {
    try { accept(await fetchMonitor(pid)); setError(null); onUpdate(); }
    catch (e: any) { setError(String(e?.message ?? e)); }
  }, [pid, onUpdate]);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    let ws: WebSocket | null = null;
    guard.current = { view: "", until: 0 }; setPending(null);
    setLive("connecting");
    const startPolling = () => {
      if (!alive || timer) return;
      setLive("polling");
      timer = window.setInterval(() => void poll(), POLL_MS);
    };
    try {
      ws = new WebSocket(monitorSocketUrl(pid));
      ws.onmessage = (e) => {
        try {
          const m = JSON.parse(String(e.data));
          if (m.type === "monitor" && alive) {
            accept(m.data); setError(null); setLive("websocket"); onUpdate();
            if (timer) { window.clearInterval(timer); timer = undefined; }
          }
        } catch { /* ignore malformed frames */ }
      };
      ws.onerror = () => startPolling();
      ws.onclose = () => startPolling();
    } catch { startPolling(); }
    const watchdog = window.setTimeout(() => { if (liveRef.current !== "websocket") startPolling(); }, 10000);
    void poll();
    return () => { alive = false; window.clearTimeout(watchdog); if (timer) window.clearInterval(timer); ws?.close(); };
  }, [pid, poll]);

  return { monitor, live, error, refresh: poll, markView, pending: pending !== null, viewStart: pending ?? monitor?.windowStart };
}

function VitalCard({ k, monitor }: { k: VitalKey; monitor: Monitor }) {
  const meta = VITAL_META[k];
  const raw = monitor.vitals[k];
  const trusted = monitor.risk.news2.parameters[k];
  const stale = monitor.assessment.staleAfterMinutes;
  const isStale = trusted ? Date.now() - new Date(trusted.effective).getTime() > stale * 60000 : false;
  const suppressedLatest = raw.latest && trusted && raw.latest.observation !== trusted.observation
    ? monitor.risk.suppressed.find((s) => s.observation === raw.latest!.observation) : undefined;
  const alert = monitor.assessment.assessable ? monitor.risk.alerts.find((a) => a.vital === k && a.level !== "NORMAL") : undefined;
  const series = raw.series.map((p) => ({ t: fmtTime(p.effective), value: p.value }));
  const b = trusted?.baseline;
  const delta = b && trusted ? trusted.value - b.median : null;
  return (
    <div data-testid={`vital-${k}`} className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-navy-700">{meta.label}</p>
        {alert ? <LevelBadge level={alert.level} /> : isStale ? <span className="rounded bg-amber-50 px-1.5 text-[11px] font-semibold text-amber-900">Stale</span> : null}
      </div>
      {trusted ? (
        <>
          <p className="mt-1 text-3xl font-semibold tabular-nums text-navy-900">
            {trusted.value.toFixed(meta.decimals)}<span className="ml-1 text-sm font-medium text-navy-500">{meta.unit}</span>
          </p>
          <p className="text-xs text-navy-500">Measured {fmtTime(trusted.effective)} ({ago(trusted.effective)})</p>
          <p className="mt-1 text-xs text-navy-700">
            {b ? <>Personal baseline {b.median.toFixed(meta.decimals)} {meta.unit} ({delta! >= 0 ? "+" : ""}{delta!.toFixed(meta.decimals)})</>
              : <span className="text-navy-500">Personal baseline: needs more readings</span>}
          </p>
        </>
      ) : (
        <p className="mt-2 text-sm text-navy-500">{raw.latest ? "No trusted reading in this period" : "No readings in this period"}</p>
      )}
      {suppressedLatest && <p className="mt-1 rounded bg-slate-100 px-2 py-1 text-[11px] text-navy-700">Latest reading {suppressedLatest.value} not used: {suppressedLatest.reason}</p>}
      <div className="mt-2 h-24" aria-label={`${meta.label} trend`}>
        {series.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series} margin={{ top: 4, right: 6, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="t" hide />
              <YAxis domain={DOMAIN[k]} tick={{ fontSize: 10, fill: "#47607c" }} width={32} tickCount={4} />
              {b && <ReferenceLine y={b.median} stroke="#0d9488" strokeDasharray="4 3" />}
              <Tooltip formatter={(v) => [`${v} ${meta.unit}`, meta.label]} labelFormatter={(l) => `at ${l}`} />
              <Line type="monotone" dataKey="value" stroke="#1d4063" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : <p className="pt-8 text-center text-xs text-navy-500">Not enough readings for a trend</p>}
      </div>
    </div>
  );
}

function RiskAssessment({ monitor }: { monitor: Monitor }) {
  const a = monitor.assessment;
  const r = monitor.risk;
  const reasons = r.alerts.filter((x) => x.level !== "NORMAL");
  return (
    <Card title="Risk assessment" right={<span className="text-xs text-navy-500">Assessed {fmtTime(monitor.evaluatedAt)}</span>}>
      {!a.assessable ? (
        <div data-testid="risk-not-assessed">
          <LevelBadge level={null} large />
          <p className="mt-2 text-sm text-navy-700">
            {a.monitoringStatus === "no_recent_data"
              ? `No readings received in the last ${a.recentWindowMinutes} minutes. Risk is not assessed without data.`
              : `Not enough trusted readings to assess: ${a.trustedVitals} of ${a.requiredTrustedVitals} vital signs available.`}
          </p>
        </div>
      ) : (
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <span data-testid="risk-level"><LevelBadge level={r.level} large /></span>
            <div className="text-sm text-navy-700">
              <p>Partial NEWS2-style score <strong>{r.news2.total}</strong> from {r.news2.measuredParameters} of {r.news2.of} parameters · SpO₂ Scale {r.news2.spo2Scale}</p>
              <p className="text-xs text-navy-500">Not measured: {r.news2.notAvailable.join(", ")}</p>
            </div>
          </div>
          {reasons.length > 0 ? (
            <ul className="mt-3 space-y-2" data-testid="risk-reasons">
              {reasons.map((x, i) => (
                <li key={i} className="rounded-lg border border-slate-200 p-2">
                  <div className="flex flex-wrap items-center gap-2"><LevelBadge level={x.level} /><span className="text-sm font-medium text-navy-900">{x.vitalLabel}</span>
                    {x.vital && <span className="text-xs text-navy-500">{x.value} {x.unit}</span>}</div>
                  <p className="mt-1 text-sm text-navy-700">{x.reason}</p>
                  <p className="mt-0.5 text-xs text-navy-500">{x.ruleType === "personal-baseline" ? "Deviation rule" : "Threshold"}: {x.rule}</p>
                  <p className="text-[11px] text-navy-500">Source: <span className="font-mono">{x.observation}</span></p>
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-sm text-navy-700">All trusted vital signs are within thresholds and the patient's personal baseline.</p>}
        </div>
      )}
      <div className="mt-3 border-t border-slate-100 pt-2 text-xs text-navy-500" data-testid="reliability">
        Data reliability: {monitor.observationCount} readings in the last {a.recentWindowMinutes} min · {a.trustedVitals}/4 vital signs with trusted readings ·{" "}
        {r.suppressedCount} reading(s) excluded as likely sensor artifacts · {a.monitoringStatus === "stale" ? "data is stale" : a.monitoringStatus === "active" ? "data is current" : "no current data"}
        {r.suppressed.length > 0 && (
          <details className="mt-1">
            <summary className="cursor-pointer font-medium text-navy-700">Excluded readings</summary>
            <ul className="mt-1 space-y-0.5">{r.suppressed.slice(-6).reverse().map((s, i) => (
              <li key={i}>{VITAL_META[s.vital]?.label ?? s.vital} {s.value} at {fmtTime(s.effective)}: {s.reason}</li>))}</ul>
          </details>
        )}
        <p className="mt-1">{r.label}</p>
      </div>
    </Card>
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
    <Card title="SpO₂ scale (clinical configuration)">
      <p className="text-sm text-navy-700">Current: <strong>Scale {status?.scale ?? 1}</strong>{status?.flag ? "" : " (default)"}</p>
      <p className="mt-1 text-xs text-navy-500">Scale 2 is for patients with a clinician-prescribed SpO₂ target of 88–92 %. It requires an attributed clinician decision and is never inferred from a diagnosis.</p>
      {status?.flag ? (
        <div className="mt-2 rounded-lg bg-slate-50 p-2 text-sm">
          <p className="text-navy-900">Scale 2 recorded by <strong>{status.flag.author}</strong> on {fmtDateTime(status.flag.since)}</p>
          <p className="text-xs text-navy-700">{status.flag.reason}</p>
          <button type="button" disabled={busy} onClick={() => run(() => clearScale2(pid))}
            className="mt-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-navy-900 disabled:opacity-50">Return to Scale 1</button>
        </div>
      ) : (
        <form className="mt-2 grid gap-2" onSubmit={(e) => { e.preventDefault(); void run(() => setScale2(pid, by.trim(), reason.trim())); }}>
          <label className="text-xs text-navy-700">Clinician name
            <input value={by} onChange={(e) => setBy(e.target.value)} required minLength={2} className="mt-0.5 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          </label>
          <label className="text-xs text-navy-700">Clinical reason
            <input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={5} placeholder="e.g. hypercapnic respiratory failure, target 88–92 %"
              className="mt-0.5 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          </label>
          <button type="submit" disabled={busy || by.trim().length < 2 || reason.trim().length < 5}
            className="justify-self-start rounded-lg bg-navy-900 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40">Record Scale 2 decision</button>
        </form>
      )}
      {status?.supportingConditions?.length ? <p className="mt-2 text-xs text-navy-500">Related conditions on record: {status.supportingConditions.map(tidyCondition).join(", ")}</p> : null}
      {err && <div className="mt-2"><ErrorNote>{err}</ErrorNote></div>}
    </Card>
  );
}

export function PatientDetail({ pid, onUpdate }: { pid: string; onUpdate: () => void }) {
  const [profile, setProfile] = useState<PatientProfile | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertEvent[] | null>(null);
  const { monitor, live, error, refresh, markView, pending, viewStart } = useMonitor(pid, onUpdate);
  const simRunning = !!monitor?.simulator?.running;
  const [alertsTick, setAlertsTick] = useState(0);
  const afterSimAction = useCallback(() => { void refresh(); setAlertsTick((n) => n + 1); }, [refresh]);
  const windowMin = monitor ? Math.round((Date.parse(monitor.evaluatedAt) - Date.parse(monitor.windowStart)) / 60000) : 0;
  const currentRun = pending || (!!monitor && windowMin < (monitor.assessment.recentWindowMinutes ?? 60) - 1);

  useEffect(() => {
    setProfile(null); setProfileError(null);
    fetchProfile(pid).then(setProfile).catch((e) => setProfileError(String(e?.message ?? e)));
  }, [pid]);
  useEffect(() => {
    let alive = true;
    const load = () => fetchAlerts(pid, 50).then((a) => alive && setAlerts(a.alerts)).catch(() => alive && setAlerts([]));
    void load();
    const t = window.setInterval(load, simRunning ? 2000 : 10000);
    return () => { alive = false; window.clearInterval(t); };
  }, [pid, simRunning, alertsTick]);

  const conditions = [...(profile?.activeConditions ?? [])].sort((a, b) => Number(!/\(disorder\)/.test(a.condition ?? "")) - Number(!/\(disorder\)/.test(b.condition ?? "")));
  return (
    <div className="space-y-5">
      <a href="#/" className="text-sm font-medium text-teal-700 hover:underline">← All patients</a>
      {profileError && <ErrorNote>Could not load the patient record: {profileError}</ErrorNote>}
      <div>
        <Card>
          {!profile ? <p className="text-sm text-navy-500">Loading patient record…</p> : (
            <div>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h2 className="text-2xl font-semibold text-navy-900" data-testid="patient-name">{displayName(profile.patient.name)}</h2>
                  <p className="text-sm text-navy-500">{profile.patient.age} years · {profile.patient.gender} · born {fmtDate(profile.patient.birthDate)} · synthetic record</p>
                </div>
                {monitor && <MonitoringBadge status={monitor.assessment.monitoringStatus} />}
              </div>
              {profile.discharge && (
                <p className="mt-2 text-sm text-navy-700">
                  Discharged <strong>{fmtDate(profile.discharge.discharged)}</strong>{profile.discharge.facility ? ` from ${profile.discharge.facility}` : ""}
                  {profile.discharge.admitted ? ` (admitted ${fmtDate(profile.discharge.admitted)})` : ""}
                </p>
              )}
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-navy-500">Conditions ({conditions.length})</h3>
                  <ul className="mt-1 space-y-0.5 text-sm text-navy-900">
                    {conditions.slice(0, 8).map((c) => <li key={c.id} className={/\(disorder\)/.test(c.condition ?? "") ? "" : "text-navy-500"}>{tidyCondition(c.condition)}</li>)}
                    {conditions.length > 8 && <li className="text-navy-500">+ {conditions.length - 8} more</li>}
                  </ul>
                </div>
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-navy-500">Active medications ({profile.activeMedications.length})</h3>
                  <ul className="mt-1 space-y-0.5 text-sm text-navy-900">
                    {profile.activeMedications.slice(0, 8).map((m) => <li key={m.id}>{m.medication}</li>)}
                    {profile.activeMedications.length > 8 && <li className="text-navy-500">+ {profile.activeMedications.length - 8} more</li>}
                  </ul>
                  {profile.allergies.length > 0 && <p className="mt-2 text-xs text-navy-700">Allergies: {profile.allergies.map((a) => a.substance).join(", ")}</p>}
                </div>
              </div>
            </div>
          )}
        </Card>
      </div>

      <SimulationPanel pid={pid} sim={monitor?.simulator} windowStart={viewStart} onNewView={markView} onChange={afterSimAction} />

      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-navy-900">Vital signs {currentRun && monitor ? <span className="font-normal text-navy-500">· current run since {fmtTime(viewStart)}</span> : null}</h2>
          <span data-testid="live-mode" className="text-xs text-navy-500">
            {live === "websocket" ? "● Live updates" : live === "polling" ? "● Updating every few seconds" : "Connecting…"}
            {monitor?.assessment.sources?.length ? ` · source: ${monitor.assessment.sources.join(", ")}` : ""}
          </span>
        </div>
        {monitor ? (
          pending || monitor.observationCount === 0
            ? <Empty>
                {pending
                  ? <span data-testid="waiting">Waiting for readings from the new run…</span>
                  : monitor.simulator?.running
                  ? <span data-testid="waiting">Waiting for readings… the simulated source has started; the first readings appear within a few seconds.</span>
                  : currentRun
                    ? <span data-testid="waiting">Waiting for readings. The view was reset at {fmtTime(monitor.windowStart)}; no readings have arrived since. Start a simulation or connect a monitoring source.</span>
                    : <>No vital-sign readings received for this patient in the last {monitor.assessment.recentWindowMinutes} minutes. No monitoring source is currently delivering data for this patient.</>}
              </Empty>
            : <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{ORDER.map((k) => <VitalCard key={k} k={k} monitor={monitor} />)}</div>
        ) : null}
      </div>

      {monitor && !pending ? <RiskAssessment monitor={monitor} /> : (
        <Card title="Risk assessment">
          {pending ? <p data-testid="risk-not-assessed" className="text-sm text-navy-700">Not assessed: waiting for readings from the new run.</p>
            : error ? <ErrorNote>{error}</ErrorNote> : <p className="text-sm text-navy-500">Loading monitoring data…</p>}
        </Card>
      )}

      <Card title="Alert history"><AlertList alerts={alerts} /></Card>
      <Scale2Panel pid={pid} status={monitor?.scale2} onChange={() => void refresh()} />
    </div>
  );
}
