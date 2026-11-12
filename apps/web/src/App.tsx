import { useCallback, useEffect, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  fetchMonitor,
  fetchObservation,
  fetchPatients,
  fetchProfile,
  fetchStatus,
  resetDemo,
  startScenario,
  stopScenario,
  clearScale2,
  createReplay,
  fetchEvidence,
  fetchLatestEvaluation,
  type Evidence,
  runEvaluation,
  setScale2,
  type DetectorMode,
  type EvaluationReport,
  replayAction,
  type Alert,
  type Monitor,
  type PatientProfile,
  type PatientSummary,
  type ReplaySpeed,
  type RiskLevel,
  type StatusResponse,
  type VitalKey,
} from "./api";
import { BRAND } from "./brand";

const POLL_MS = 1500;

const RISK_STYLE: Record<RiskLevel, { badge: string; panel: string; dot: string }> = {
  NORMAL: { badge: "bg-teal-600 text-white", panel: "border-teal-200 bg-teal-50", dot: "bg-teal-600" },
  WATCH: { badge: "bg-amber-500 text-white", panel: "border-amber-200 bg-amber-50", dot: "bg-amber-500" },
  REVIEW: { badge: "bg-orange-600 text-white", panel: "border-orange-200 bg-orange-50", dot: "bg-orange-600" },
  URGENT: { badge: "bg-red-600 text-white", panel: "border-red-200 bg-red-50", dot: "bg-red-600" },
};
const RANK: Record<RiskLevel, number> = { NORMAL: 0, WATCH: 1, REVIEW: 2, URGENT: 3 };

// Prototype WATCH lines drawn on the charts (mirror apps/api/app/risk.py THRESHOLDS).
const VITALS: { key: VitalKey; short: string; watch: number[]; domain: [number, number]; decimals: number }[] = [
  { key: "heart_rate", short: "HR", watch: [100, 50], domain: [40, 150], decimals: 0 },
  { key: "spo2", short: "SpO₂", watch: [95], domain: [84, 100], decimals: 0 },
  { key: "respiratory_rate", short: "RR", watch: [21], domain: [8, 36], decimals: 0 },
  { key: "body_temperature", short: "Temp", watch: [38], domain: [35.5, 40], decimals: 1 },
];

const displayName = (n: string) => n.replace(/\d+/g, "").replace(/\s+/g, " ").trim();
const time = (iso?: string | null) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
const day = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" }) : "—");
const tidy = (s?: string) => (s ?? "").replace(/\s*\((disorder|finding|situation|procedure)\)$/i, "");

function Card({ title, children, right, className = "" }: { title: string; children: React.ReactNode; right?: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-navy-500">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

function FhirPill({ status }: { status: StatusResponse | null | "down" }) {
  const fhir = status && status !== "down" ? status.services.fhir : null;
  const ok = fhir?.status === "ok" && fhir.isR4;
  const text = status === null ? "Checking FHIR…" : status === "down" ? "API unreachable" : ok ? `HAPI FHIR R4 connected · ${fhir?.fhirVersion}` : `HAPI FHIR ${fhir?.status ?? "unknown"}`;
  return (
    <span data-testid="fhir-status" className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${ok ? "bg-teal-500/20 text-teal-50" : "bg-red-500/30 text-white"}`}>
      <span className={`h-2 w-2 rounded-full ${ok ? "bg-teal-300" : "bg-red-300"}`} />
      {text}
    </span>
  );
}

function ReplayPanel({ patientId, monitor, onAction, busy }: {
  patientId: string | null;
  monitor: Monitor | null;
  onAction: (fn: () => Promise<unknown>) => Promise<void>;
  busy: boolean;
}) {
  const [scenario, setScenario] = useState("deterioration");
  const [speed, setSpeed] = useState<ReplaySpeed>("10x");
  const [duration, setDuration] = useState(120);
  const r = monitor?.replay ?? null;
  const st = r?.state;
  // Any non-active session (created, stopped, completed, error) can be replaced by a new one.
  const canStart = !!patientId && !(st === "running" || st === "paused");
  const btn = "rounded-lg px-3 py-1.5 text-sm font-semibold disabled:opacity-40";
  return (
    <Card title="Replay engine (simulated time)" right={<span className="text-[11px] text-navy-500">deterministic · seeded</span>}>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-navy-500">Scenario
          <select aria-label="Replay scenario" value={scenario} onChange={(e) => setScenario(e.target.value)} className="mt-0.5 block rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-navy-900">
            <option value="stable">Stable Recovery</option>
            <option value="deterioration">Gradual Deterioration</option>
          </select>
        </label>
        <label className="text-xs text-navy-500">Duration
          <select aria-label="Replay duration" value={duration} onChange={(e) => setDuration(Number(e.target.value))} className="mt-0.5 block rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-navy-900">
            <option value={30}>30 min</option>
            <option value={120}>2 h</option>
            <option value={1440}>24 h</option>
          </select>
        </label>
        <label className="text-xs text-navy-500">Speed
          <select aria-label="Replay speed" value={speed} onChange={(e) => setSpeed(e.target.value as ReplaySpeed)} className="mt-0.5 block rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-navy-900">
            <option value="1x">1×</option>
            <option value="5x">5×</option>
            <option value="10x">10×</option>
            <option value="batch">Batch (no waiting)</option>
          </select>
        </label>
        <button type="button" aria-label="Start replay" disabled={!canStart || busy} className={`${btn} bg-teal-700 text-white hover:bg-teal-600`}
          onClick={() => onAction(async () => {
            const s = await createReplay({ patientId: patientId!, scenario, speed, durationMinutes: duration });
            await replayAction(s.sessionId, "start");
          })}>▶ Start</button>
        <button type="button" aria-label="Start reset session" disabled={!r || st !== "created" || busy} className={`${btn} border border-slate-300 bg-white text-navy-900`}
          onClick={() => onAction(() => replayAction(r!.sessionId, "start"))}>Start reset session</button>
        <button type="button" aria-label="Pause replay" disabled={st !== "running" || busy} className={`${btn} border border-slate-300 bg-white text-navy-900`}
          onClick={() => onAction(() => replayAction(r!.sessionId, "pause"))}>❚❚ Pause</button>
        <button type="button" aria-label="Resume replay" disabled={!(st === "paused" || st === "error") || busy} className={`${btn} border border-slate-300 bg-white text-navy-900`}
          onClick={() => onAction(() => replayAction(r!.sessionId, "resume"))}>▶ Resume</button>
        <button type="button" aria-label="Stop replay" disabled={!(st === "running" || st === "paused") || busy} className={`${btn} border border-slate-300 bg-white text-navy-900`}
          onClick={() => onAction(() => replayAction(r!.sessionId, "stop"))}>■ Stop</button>
        <button type="button" aria-label="Reset replay" disabled={!r || busy} className={`${btn} border border-slate-300 bg-white text-navy-900`}
          onClick={() => onAction(() => replayAction(r!.sessionId, "reset"))}>↺ Reset</button>
      </div>
      {r ? (
        <div className="mt-3 text-xs text-navy-700" aria-live="polite" data-testid="replay-status">
          <div className="flex flex-wrap justify-between gap-2">
            <span><strong>{r.scenarioName}</strong> · seed {r.seed} · {r.speed} · <span data-testid="replay-state" className="font-semibold uppercase">{r.state}</span></span>
            <span>simulated time {new Date(r.simulatedNow).toLocaleString()}</span>
          </div>
          <div className="mt-1 h-2 rounded-full bg-slate-100">
            <div className="h-2 rounded-full bg-teal-600 transition-all" style={{ width: `${Math.round(100 * r.progress)}%` }} />
          </div>
          <p className="mt-1">
            {r.persisted}/{r.eventsTotal} observations confirmed by HAPI · {r.batches} batches{r.failedBatches ? ` · ${r.failedBatches} failed (retry with Resume)` : ""}
            {r.existing ? ` · ${r.existing} already stored (idempotent retry)` : ""}
          </p>
          {r.lastError && <p className="mt-1 rounded bg-red-50 p-2 text-red-800">{r.lastError}</p>}
          <p className="mt-1 text-[11px] text-navy-500">Session {r.sessionId}{r.resetFrom ? ` (reset of ${r.resetFrom})` : ""} · fingerprint {r.fingerprint.slice(0, 12)}…</p>
        </div>
      ) : (
        <p className="mt-3 text-xs text-navy-500">Replays seeded scenarios on a simulated clock and stores every reading in HAPI in batches. Measurement times are in the past; ingestion time is recorded separately.</p>
      )}
    </Card>
  );
}

function Scale2Card({ patientId, status, onAction, busy }: { patientId: string | null; status: import("./api").Scale2Status | null; onAction: (fn: () => Promise<unknown>) => Promise<void>; busy: boolean }) {
  const [by, setBy] = useState("");
  const [reason, setReason] = useState("");
  return (
    <Card title="SpO2 Scale 2 eligibility (FHIR Flag)">
      <p className="text-xs text-navy-700">{status?.rule ?? "Scale 2 needs an attributed clinician decision; a diagnosis alone never switches the scale."}</p>
      {status?.flag ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded bg-navy-900 px-2 py-0.5 text-xs font-bold text-white">Scale 2 active</span>
          <span className="text-navy-700">{status.flag.reference} · by {status.flag.author} · {status.flag.reason}</span>
          <button type="button" disabled={busy} onClick={() => onAction(() => clearScale2(patientId!))} className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-semibold">Deactivate</button>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <input aria-label="Prescribed by" placeholder="Prescribed by (clinician)" value={by} onChange={(e) => setBy(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          <input aria-label="Reason" placeholder="Reason, e.g. target 88–92% for hypercapnic respiratory failure" value={reason} onChange={(e) => setReason(e.target.value)} className="min-w-0 flex-[2] rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          <button type="button" disabled={!patientId || busy || by.trim().length < 2 || reason.trim().length < 5}
            onClick={() => onAction(() => setScale2(patientId!, by.trim(), reason.trim()))}
            className="rounded-lg bg-navy-900 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40">Record Scale 2 decision</button>
        </div>
      )}
      <p className="mt-1 text-[11px] text-navy-500">Supporting conditions on record: {status?.supportingConditions.length ? status.supportingConditions.join(", ") : "none"}</p>
    </Card>
  );
}

function EvaluationCard({ patientId }: { patientId: string | null }) {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { fetchLatestEvaluation().then(setReport).catch(() => setReport(null)); }, []);
  const cell = (v: number | boolean | null | undefined, suffix = "") => (v === null || v === undefined ? "—" : typeof v === "boolean" ? (v ? "yes" : "no") : `${v}${suffix}`);
  return (
    <Card title="Scenario replay evaluation: fixed vs personalized" right={
      <button type="button" disabled={!patientId || running} onClick={async () => {
        setRunning(true); setErr(null);
        try { setReport(await runEvaluation(patientId!)); } catch (e: any) { setErr(String(e?.message ?? e)); } finally { setRunning(false); }
      }} className="rounded-lg bg-teal-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
        {running ? "Running (about 45 s)…" : "Run evaluation (4 scenarios × 4 h)"}
      </button>}>
      {err && <p className="mb-2 rounded bg-red-50 p-2 text-xs text-red-800">{err}</p>}
      {!report ? <p className="text-sm text-navy-500">No evaluation yet. Each run replays seeded scenarios into HAPI, reads them back and scores both detector modes.</p> : (
        <div className="overflow-x-auto" data-testid="evaluation">
          <p className="mb-2 text-[11px] text-navy-500">{report.dataSource} · {report.durationMinutes} min per scenario at {report.intervalSeconds} s · generated {new Date(report.generatedAt).toLocaleString()} · SpO2 Scale {report.spo2Scale}</p>
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="uppercase text-navy-500">
              <tr><th className="py-1 pr-2">Scenario</th><th className="pr-2">Mode</th><th className="pr-2">Alert episodes</th><th className="pr-2">Alerts / patient-day</th><th className="pr-2">False alert episodes (artifact)</th><th className="pr-2">Onset → first WATCH</th><th className="pr-2">Lead before critical</th><th className="pr-2">Explained</th><th className="pr-2">Peak</th><th>FHIR confirmed</th></tr>
            </thead>
            <tbody>
              {report.scenarios.flatMap((s) => (["fixed", "personalized"] as DetectorMode[]).map((m) => {
                const v = s.modes[m];
                return (
                  <tr key={s.scenario + m} className="border-t border-slate-100">
                    <td className="py-1 pr-2 font-medium text-navy-900">{m === "fixed" ? s.scenarioName : ""}</td>
                    <td className="pr-2">{m}</td>
                    <td className="pr-2">{v.alertEpisodes}</td>
                    <td className="pr-2">{cell(v.alertsPerPatientDay)}</td>
                    <td className="pr-2">{v.falseAlertEpisodes} ({v.artifactAlertEpisodes})</td>
                    <td className="pr-2">{cell(v.onsetToFirstWatchMin, " min")}</td>
                    <td className="pr-2">{cell(v.leadTimeBeforeCriticalMin, " min")}</td>
                    <td className="pr-2">{cell(v.explainabilityPct, "%")}</td>
                    <td className="pr-2">{v.peakLevel}</td>
                    <td>{m === "fixed" ? `${s.fhirCompliance.confirmedPct}% · ${s.fhirCompliance.sampleErrors} $validate errors` : ""}</td>
                  </tr>
                );
              }))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-navy-500">Simulated, seeded scenarios only; not clinical evidence. "Critical" is a scripted ground-truth point (≥2 of SpO2 ≤91, pulse ≥131, RR ≥25), never visible to the detector.</p>
        </div>
      )}
    </Card>
  );
}

const STATUS_STYLE: Record<string, string> = {
  PASS: "bg-teal-600 text-white", PARTIAL: "bg-amber-500 text-white", FAIL: "bg-red-600 text-white", BLOCKED: "bg-slate-500 text-white",
};

function EvidenceCard() {
  const [ev, setEv] = useState<Evidence | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => fetchEvidence().then((e) => { setEv(e); setErr(null); }).catch((e) => setErr(String(e?.message ?? e)));
  useEffect(() => { void load(); }, []);
  return (
    <Card title="Judge Evidence Console" right={<button type="button" onClick={() => void load()} className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-semibold">Recompute</button>}>
      {err && <p className="text-xs text-red-700">{err}</p>}
      {!ev ? <p className="text-sm text-navy-500">Computing evidence from HAPI and saved reports…</p> : (
        <div data-testid="evidence">
          <p className="mb-2 text-[11px] text-navy-500">Computed {new Date(ev.generatedAt).toLocaleString()} from live HAPI data, the SQLite event store and saved reports. Data: {Object.entries(ev.dataProvenance).map(([k, v]) => `${k}: ${v}`).join(" · ")}</p>
          <ul className="space-y-2">
            {ev.requirements.map((r) => (
              <li key={r.id} className="rounded-lg border border-slate-200 p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-bold ${STATUS_STYLE[r.status]}`}>{r.status}</span>
                  <span className="text-sm font-semibold text-navy-900">{r.id}. {r.requirement}</span>
                </div>
                <ul className="mt-1 text-xs text-navy-700">{r.evidence.filter(Boolean).map((e, i) => <li key={i}>• {e}</li>)}</ul>
                <p className="mt-0.5 font-mono text-[10px] text-navy-500">verify: {r.verify}</p>
              </li>
            ))}
          </ul>
          {ev.acceptance ? (
            <div className="mt-3 overflow-x-auto">
              <p className="text-xs font-semibold text-navy-900">Last acceptance run: {new Date(ev.acceptance.ranAt).toLocaleString()} · <code>{ev.acceptance.command}</code>{ev.acceptance.commit ? ` · commit ${ev.acceptance.commit.slice(0, 7)}` : ""}</p>
              <table className="mt-1 w-full min-w-[560px] text-left text-xs">
                <tbody>
                  {Object.entries(ev.acceptance.checks).map(([k, c]) => (
                    <tr key={k} className="border-t border-slate-100 align-top">
                      <td className="py-1 pr-2"><span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${STATUS_STYLE[c.status] ?? "bg-slate-200"}`}>{c.status}</span></td>
                      <td className="pr-2 font-medium text-navy-900">{k.replace(/_/g, " ")}</td>
                      <td className="text-navy-700">{c.evidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="mt-2 text-xs text-navy-500">No acceptance run recorded yet: run <code>scripts/acceptance.py</code>.</p>}
        </div>
      )}
    </Card>
  );
}

function VitalCard({ v, monitor, alerts }: { v: (typeof VITALS)[number]; monitor: Monitor | null; alerts: Alert[] }) {
  const data = monitor?.vitals[v.key];
  const latest = data?.latest;
  const worst = alerts.filter((a) => a.vital === v.key).sort((a, b) => RANK[b.level] - RANK[a.level])[0];
  const level: RiskLevel = worst?.level ?? "NORMAL";
  const series = (data?.series ?? []).map((p) => ({ t: time(p.effective), value: p.value, obs: p.observation }));
  return (
    <div data-testid={`vital-${v.key}`} className={`rounded-2xl border bg-white p-4 shadow-sm ${latest ? RISK_STYLE[level].panel : "border-slate-200"}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-navy-500">{data?.label ?? v.short}</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums text-navy-900">
            {latest ? latest.value.toFixed(v.decimals) : "—"}
            <span className="ml-1 text-base font-medium text-navy-500">{data?.unit}</span>
          </p>
        </div>
        {latest && <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${RISK_STYLE[level].badge}`}>{level}</span>}
      </div>
      <div className="mt-2 h-24">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 4, right: 6, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="t" hide />
            <YAxis domain={v.domain} tick={{ fontSize: 10, fill: "#47607c" }} width={34} tickCount={4} />
            {v.watch.map((w) => (
              <ReferenceLine key={w} y={w} stroke="#f59e0b" strokeDasharray="4 3" />
            ))}
            <Tooltip formatter={(val) => [`${val} ${data?.unit ?? ""}`, data?.label ?? ""]} labelFormatter={(l) => `at ${l}`} />
            <Line type="monotone" dataKey="value" stroke="#0d9488" strokeWidth={2.5} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 truncate text-[11px] text-navy-500">
        {latest ? `${latest.observation} · ${time(latest.effective)}` : "No readings in this window"}
      </p>
    </div>
  );
}

export default function App() {
  const [status, setStatus] = useState<StatusResponse | null | "down">(null);
  const [patients, setPatients] = useState<PatientSummary[] | null>(null);
  const [patientsError, setPatientsError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [profile, setProfile] = useState<PatientProfile | null>(null);
  const [monitor, setMonitor] = useState<Monitor | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [readBack, setReadBack] = useState<{ id: string; at: string; body: Record<string, any> } | { error: string } | null>(null);
  const inFlight = useRef(false);
  const [mode, setMode] = useState<DetectorMode>("personalized");
  const [live, setLive] = useState<"websocket" | "polling" | "connecting">("connecting");
  const liveRef = useRef(live);
  liveRef.current = live;

  useEffect(() => {
    const load = () => fetchStatus().then(setStatus).catch(() => setStatus("down"));
    load();
    const t = window.setInterval(load, 10000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    fetchPatients()
      .then((r) => {
        setPatients(r.patients);
        setSelected((s) => s ?? r.patients[0]?.id ?? null);
      })
      .catch((e) => setPatientsError(String(e.message ?? e)));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setProfile(null);
    setMonitor(null);
    setReadBack(null);
    fetchProfile(selected).then(setProfile).catch(() => setProfile(null));
  }, [selected]);

  const poll = useCallback(async () => {
    if (!selected || inFlight.current) return;
    inFlight.current = true;
    try {
      setMonitor(await fetchMonitor(selected, mode));
    } catch {
      /* keep last good frame; status pill shows connectivity */
    } finally {
      inFlight.current = false;
    }
  }, [selected, mode]);

  // Live updates: WebSocket push from /ws/monitor/{id}; falls back to polling if the socket fails or stays silent.
  useEffect(() => {
    if (!selected) return;
    let alive = true;
    let timer: number | undefined;
    let ws: WebSocket | null = null;
    setLive("connecting");
    const startPolling = () => {
      if (!alive || timer) return;
      setLive("polling");
      timer = window.setInterval(() => void poll(), POLL_MS);
    };
    try {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${scheme}://${window.location.host}/ws/monitor/${encodeURIComponent(selected)}?mode=${mode}`);
      ws.onmessage = (e) => {
        try {
          const m = JSON.parse(String(e.data));
          if (m.type === "monitor" && alive) {
            setMonitor(m.data);
            setLive("websocket");
            if (timer) { window.clearInterval(timer); timer = undefined; }
          }
        } catch { /* ignore malformed frames */ }
      };
      ws.onerror = () => startPolling();
      ws.onclose = () => startPolling();
    } catch {
      startPolling();
    }
    // Allow time for the first push (one monitor build); then fall back to polling.
    const watchdog = window.setTimeout(() => { if (liveRef.current !== "websocket") startPolling(); }, 10000);
    void poll();
    return () => {
      alive = false;
      window.clearTimeout(watchdog);
      if (timer) window.clearInterval(timer);
      ws?.close();
    };
  }, [poll, selected, mode]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      setReadBack(null);
      await poll();
    } catch (e: any) {
      setActionError(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const doReadBack = async () => {
    const id = monitor?.fhirProof?.id;
    if (!id) return;
    try {
      setReadBack({ id, at: new Date().toISOString(), body: await fetchObservation(id) });
    } catch (e: any) {
      setReadBack({ error: String(e?.message ?? e) });
    }
  };

  const sim = monitor?.simulator ?? null;
  const running = !!sim?.running;
  const risk = monitor?.risk;
  const level: RiskLevel = risk?.level ?? "NORMAL";
  const current = patients?.find((p) => p.id === selected);
  const conditions = [...(profile?.activeConditions ?? [])].sort((a, b) => Number(!/\(disorder\)/.test(a.condition ?? "")) - Number(!/\(disorder\)/.test(b.condition ?? "")));

  return (
    <div className="flex min-h-screen flex-col bg-surface font-sans">
      <header className="bg-navy-900 text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div className="flex items-center gap-3">
            <img src="/favicon.svg" alt="" className="h-10 w-10" />
            <div>
              <h1 className="text-xl font-bold tracking-wide">AROGYA DRISHTI</h1>
              <p className="text-sm text-teal-50/80">{BRAND.tagline}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <FhirPill status={status} />
            <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium">Round 1 MVP</span>
          </div>
        </div>
        <div className="bg-teal-700/90">
          <p role="note" className="mx-auto max-w-7xl px-6 py-1.5 text-xs font-medium text-white">
            {BRAND.disclaimer} Synthetic patients (Synthea) · simulated wearable data · prototype risk rules, not NEWS2.
          </p>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-5 px-4 py-6 sm:px-6 lg:grid-cols-[300px_minmax(0,1fr)]">
        {/* ---------------- patients ---------------- */}
        <aside className="min-w-0 space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-navy-500">Discharged patients</h2>
          {patientsError && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-800">Could not load patients: {patientsError}</p>}
          {!patients && !patientsError && <p className="text-sm text-navy-500">Loading patients from HAPI FHIR…</p>}
          <ul className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:mx-0 lg:block lg:space-y-2 lg:overflow-visible lg:px-0">
            {patients?.map((p) => (
              <li key={p.id} className="w-64 shrink-0 lg:w-auto">
                <button
                  type="button"
                  onClick={() => setSelected(p.id)}
                  aria-pressed={p.id === selected}
                  className={`w-full rounded-xl border p-3 text-left transition ${p.id === selected ? "border-teal-600 bg-teal-50 ring-2 ring-teal-600/30" : "border-slate-200 bg-white hover:border-teal-300"}`}
                >
                  <p className="font-semibold text-navy-900">{displayName(p.name)}</p>
                  <p className="text-xs text-navy-500">
                    {p.age ?? "?"} y · {p.gender ?? "—"} · discharged {day(p.lastDischarge)}
                  </p>
                  <p className="mt-1 text-xs text-navy-700">
                    {p.activeConditions} active conditions · {p.activeMedications} active meds
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <div className="min-w-0 space-y-5">
          {/* ---------------- patient + controls ---------------- */}
          <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <Card title="Patient profile" right={<span className="text-[11px] text-navy-500">FHIR Patient/{selected?.slice(0, 8)}…</span>}>
              {!profile ? (
                <p className="text-sm text-navy-500">{selected ? "Loading profile from HAPI FHIR…" : "Select a patient."}</p>
              ) : (
                <div>
                  <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                    <p className="text-2xl font-semibold text-navy-900" data-testid="patient-name">{displayName(profile.patient.name)}</p>
                    <p className="text-sm text-navy-500">
                      {profile.patient.age} years · {profile.patient.gender} · born {profile.patient.birthDate}
                    </p>
                  </div>
                  {profile.discharge && (
                    <p className="mt-1 text-sm text-navy-700">
                      Last discharge <strong>{day(profile.discharge.discharged)}</strong> from {profile.discharge.facility ?? "hospital"} · {profile.discharge.inpatientStays} inpatient stay(s)
                    </p>
                  )}
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <div>
                      <h3 className="text-xs font-semibold uppercase text-navy-500">Active conditions ({conditions.length})</h3>
                      <ul className="mt-1 space-y-0.5 text-sm text-navy-900">
                        {conditions.slice(0, 6).map((c) => <li key={c.id} className={/\(disorder\)/.test(c.condition ?? "") ? "" : "text-navy-500"}>• {tidy(c.condition)}</li>)}
                        {conditions.length > 6 && <li className="text-navy-500">+ {conditions.length - 6} more</li>}
                      </ul>
                    </div>
                    <div>
                      <h3 className="text-xs font-semibold uppercase text-navy-500">Active medications ({profile.activeMedications.length})</h3>
                      <ul className="mt-1 space-y-0.5 text-sm text-navy-900">
                        {profile.activeMedications.slice(0, 6).map((m) => <li key={m.id}>• {m.medication}</li>)}
                        {profile.activeMedications.length > 6 && <li className="text-navy-500">+ {profile.activeMedications.length - 6} more</li>}
                      </ul>
                    </div>
                  </div>
                </div>
              )}
            </Card>

            <Card title="Judge demo controls">
              <div className="space-y-2">
                <button type="button" disabled={!selected || busy} onClick={() => act(() => startScenario(selected!, "stable"))}
                  className="w-full rounded-xl bg-teal-700 px-4 py-3 text-sm font-semibold text-white shadow hover:bg-teal-600 disabled:opacity-50">
                  ▶ Demonstrate Stable Recovery
                </button>
                <button type="button" disabled={!selected || busy} onClick={() => act(() => startScenario(selected!, "deterioration"))}
                  className="w-full rounded-xl bg-navy-900 px-4 py-3 text-sm font-semibold text-white shadow hover:bg-navy-700 disabled:opacity-50">
                  ▶ Demonstrate Gradual Deterioration
                </button>
                <div className="grid grid-cols-2 gap-2">
                  <button type="button" disabled={!running || busy} onClick={() => act(stopScenario)}
                    className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-navy-900 hover:bg-slate-50 disabled:opacity-40">
                    ■ Stop
                  </button>
                  <button type="button" disabled={!selected || busy} onClick={() => act(() => resetDemo(selected!))}
                    className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-navy-900 hover:bg-slate-50 disabled:opacity-40">
                    ↺ Reset demo
                  </button>
                </div>
              </div>
              <div className="mt-4" aria-live="polite">
                {sim ? (
                  <>
                    <div className="flex justify-between text-xs text-navy-700">
                      <span><strong>{sim.scenarioLabel}</strong> · {running ? "running" : sim.stopped ? "stopped" : "finished"}</span>
                      <span>{sim.step}/{sim.totalSteps}</span>
                    </div>
                    <div className="mt-1 h-2 rounded-full bg-slate-100">
                      <div className="h-2 rounded-full bg-teal-600 transition-all" style={{ width: `${(100 * sim.step) / Math.max(1, sim.totalSteps)}%` }} />
                    </div>
                    <p className="mt-1 text-[11px] text-navy-500">
                      {sim.accepted} observations stored in HAPI · {sim.rejected} rejected{sim.lastError ? ` · ${sim.lastError}` : ""}
                    </p>
                  </>
                ) : (
                  <p className="text-xs text-navy-500">Simulator idle for this patient. Readings are posted to <code>POST /api/fhir/Observation</code> every {2} s.</p>
                )}
                {actionError && <p className="mt-2 rounded bg-red-50 p-2 text-xs text-red-800">{actionError}</p>}
              </div>
            </Card>
          </div>

          <ReplayPanel patientId={selected} monitor={monitor} onAction={act} busy={busy} />

          {/* ---------------- risk ---------------- */}
          <section data-testid="risk-panel" className={`rounded-2xl border p-5 shadow-sm ${RISK_STYLE[level].panel}`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span data-testid="risk-level" className={`rounded-xl px-4 py-2 text-2xl font-bold tracking-wide ${RISK_STYLE[level].badge}`}>{level}</span>
                <div>
                  <p className="text-sm font-semibold text-navy-900">Current risk level</p>
                  <p className="text-sm text-navy-700">{risk?.summary ?? "Waiting for data…"}</p>
                </div>
              </div>
              <div className="flex flex-col items-end gap-1">
                <div role="group" aria-label="Detection mode" className="inline-flex overflow-hidden rounded-lg border border-slate-300 bg-white text-xs font-semibold">
                  {(["personalized", "fixed"] as DetectorMode[]).map((m) => (
                    <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}
                      className={`px-3 py-1.5 ${mode === m ? "bg-navy-900 text-white" : "text-navy-700 hover:bg-slate-50"}`}>
                      {m === "personalized" ? "Personalized + artifact filter" : "Fixed thresholds"}
                    </button>
                  ))}
                </div>
                <span data-testid="live-mode" className="text-[11px] font-semibold text-navy-700">
                  {live === "websocket" ? "● Live via WebSocket" : live === "polling" ? "● Live via polling (WebSocket unavailable)" : "Connecting…"}
                </span>
                <p className="text-[11px] text-navy-500">
                  {monitor ? `${monitor.observationCount} observations since ${time(monitor.windowStart)} · evaluated ${time(monitor.evaluatedAt)}` : ""}
                </p>
              </div>
            </div>
            {risk?.news2 && (
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs" data-testid="news2">
                <span className="rounded-lg bg-white/70 px-2 py-1 font-semibold text-navy-900 ring-1 ring-black/5">
                  NEWS2-style {risk.news2.total} (partial {risk.news2.measuredParameters}/{risk.news2.of})
                </span>
                {Object.entries(risk.news2.parameters).map(([k, p]) => (
                  <span key={k} className="rounded-lg bg-white/70 px-2 py-1 text-navy-700 ring-1 ring-black/5">
                    {k.replace("_", " ")} {p.value} → <strong>{p.score}</strong>{p.baseline ? ` · baseline ${p.baseline.median}` : ""}
                  </span>
                ))}
                <span className={`rounded-lg px-2 py-1 font-semibold ${risk.news2.spo2Scale === 2 ? "bg-navy-900 text-white" : "bg-white/70 text-navy-700 ring-1 ring-black/5"}`}>
                  SpO2 Scale {risk.news2.spo2Scale}
                </span>
                <span className="text-navy-500">not measured: {risk.news2.notAvailable.join(", ")}</span>
              </div>
            )}
            {!!risk?.suppressedCount && (
              <details className="mt-2 text-xs text-navy-700" data-testid="suppressed">
                <summary className="cursor-pointer font-semibold">Sensor Trust Engine suppressed {risk.suppressedCount} reading(s)</summary>
                <ul className="mt-1 space-y-0.5">
                  {risk.suppressed?.slice(-6).map((s, i) => <li key={i}>• {s.vital.replace("_", " ")} {s.value} at {time(s.effective)}: {s.reason} <span className="font-mono text-[10px]">{s.observation}</span></li>)}
                </ul>
              </details>
            )}
            {risk && risk.alerts.length > 0 && (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-xs uppercase text-navy-500">
                    <tr><th className="py-1 pr-3">Level</th><th className="pr-3">Vital</th><th className="pr-3">Measured</th><th className="pr-3">Rule applied</th><th className="pr-3">Observation</th><th>Why</th></tr>
                  </thead>
                  <tbody>
                    {risk.alerts.map((a, i) => (
                      <tr key={i} className="border-t border-black/5 align-top">
                        <td className="py-1.5 pr-3"><span className={`rounded px-1.5 py-0.5 text-[11px] font-bold ${RISK_STYLE[a.level].badge}`}>{a.level}</span></td>
                        <td className="pr-3 font-medium text-navy-900">{a.vitalLabel}</td>
                        <td className="pr-3 tabular-nums">{a.value} {a.unit}</td>
                        <td className="pr-3 text-navy-700">{a.rule} <span className="text-[11px] text-navy-500">({a.ruleType})</span></td>
                        <td className="max-w-[160px] truncate pr-3 font-mono text-[11px] text-navy-700" title={a.observation}>{a.observation}</td>
                        <td className="text-navy-700">{a.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="mt-3 text-[11px] text-navy-500">{risk?.label}</p>
          </section>

          {/* ---------------- vitals ---------------- */}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {VITALS.map((v) => <VitalCard key={v.key} v={v} monitor={monitor} alerts={risk?.alerts ?? []} />)}
          </div>

          {/* ---------------- FHIR proof ---------------- */}
          <Card title="FHIR persistence proof" right={<span className="text-[11px] text-navy-500">{current ? displayName(current.name) : ""}</span>}>
            {!monitor?.fhirProof ? (
              <p className="text-sm text-navy-500">No observation stored in this monitoring window yet. Start a scenario.</p>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm" data-testid="fhir-proof">
                  <dt className="text-navy-500">Latest Observation</dt><dd className="font-mono font-semibold text-navy-900">{monitor.fhirProof.observation}</dd>
                  <dt className="text-navy-500">HAPI versionId</dt><dd>{monitor.fhirProof.versionId}</dd>
                  <dt className="text-navy-500">Stored at (HAPI)</dt><dd>{monitor.fhirProof.lastUpdated}</dd>
                  {monitor.fhirProof.replay ? (
                    <>
                      <dt className="text-navy-500">Persisted via</dt><dd>replay batch {monitor.fhirProof.replay.batch} · HAPI transaction confirmed ({monitor.fhirProof.replay.persistStatus === "created" ? "201 Created" : "200 already stored"})</dd>
                      <dt className="text-navy-500">Measured (simulated)</dt><dd>{monitor.fhirProof.replay.measuredAt}</dd>
                      <dt className="text-navy-500">Validation</dt><dd>{monitor.fhirProof.replay.validation}</dd>
                    </>
                  ) : (
                    <>
                      <dt className="text-navy-500">HAPI $validate errors</dt><dd>{monitor.fhirProof.hapiValidationErrors ?? "—"}</dd>
                      <dt className="text-navy-500">Read-back on ingest</dt><dd>{monitor.fhirProof.readBackMatches === true ? "✔ matches what was sent" : monitor.fhirProof.readBackMatches === false ? "✖ mismatch" : "—"}</dd>
                    </>
                  )}
                  <dt className="text-navy-500">HAPI URL</dt><dd className="truncate"><a className="text-teal-700 underline" href={monitor.fhirProof.hapiUrl} target="_blank" rel="noreferrer">{monitor.fhirProof.hapiUrl}</a></dd>
                </dl>
                <div>
                  <button type="button" onClick={doReadBack} className="rounded-lg bg-teal-700 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-600">
                    Read back from HAPI now
                  </button>
                  {readBack && "error" in readBack && <p className="mt-2 text-sm text-red-700">Read-back failed: {readBack.error}</p>}
                  {readBack && "body" in readBack && (
                    <div className="mt-2 rounded-lg bg-slate-50 p-3 text-xs text-navy-900" data-testid="read-back">
                      <p className="font-semibold">GET Observation/{readBack.id} → {readBack.body.resourceType} (live from HAPI at {time(readBack.at)})</p>
                      <p>status: {readBack.body.status} · code: {readBack.body.code?.coding?.[0]?.system}|{readBack.body.code?.coding?.[0]?.code}</p>
                      <p>value: {readBack.body.valueQuantity?.value} {readBack.body.valueQuantity?.code} · subject: {readBack.body.subject?.reference?.slice(0, 20)}…</p>
                      <p>meta.versionId {readBack.body.meta?.versionId} · profile {readBack.body.meta?.profile?.[0]}</p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </Card>
          <Scale2Card patientId={selected} status={monitor?.scale2 ?? null} onAction={act} busy={busy} />
          <EvaluationCard patientId={selected} />
          <EvidenceCard />
        </div>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <p className="mx-auto max-w-7xl px-6 py-3 text-xs text-navy-700">
          {BRAND.name} · {BRAND.disclaimer} All patients are synthetic. Risk levels come from a prototype rules engine for demonstration only.
        </p>
      </footer>
    </div>
  );
}
