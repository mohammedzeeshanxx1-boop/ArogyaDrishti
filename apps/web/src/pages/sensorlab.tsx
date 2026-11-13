import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  fetchLabPrepared, fetchPatientList, fetchSensorLabRun, startLabRun,
  type LabAnalysis, type LabScenario, type LabStep, type SensorMetrics, type VitalKey,
} from "../api";
import { BRAND } from "../brand";
import { IconAlert, IconCheck, IconShield } from "../components/icons";
import { ErrorNote, LevelBadge, VITAL_META, displayName } from "../components/ui";

/** Sensor Reliability Lab. Uses the existing replay runs (POST /api/early-detection/runs), the existing engine
 *  output and the labelled fixed-threshold comparator; metrics are computed server-side from the scenario labels. */

type Mode = "fault" | "deterioration";
const SCENARIO: Record<Mode, LabScenario> = { fault: "artifact", deterioration: "deterioration" };
const STEP_MS: Record<Mode, number> = { fault: 330, deterioration: 380 };
const HOLD = 4;
const VITALS: VitalKey[] = ["spo2", "heart_rate", "respiratory_rate", "body_temperature"];
const tPlus = (m: number) => `T+${Math.round(m)} min`;
const minutesAt = (a: LabAnalysis, i: number) => (Date.parse(a.steps[i].t) - Date.parse(a.start)) / 60000;

/** Plain-language sensor-quality message chosen from the engine's actual classification reason. */
export function sensorMessage(vital: VitalKey, reason: string): string {
  const r = reason.toLowerCase();
  if (r.includes("probe-off")) {
    return vital === "spo2"
      ? "Possible sensor disconnection detected. Oxygen readings may be unreliable. Please check the wearable device."
      : "Possible sensor disconnection detected. Heart-rate readings may be unreliable. Please check the wearable device.";
  }
  if (r.includes("jump") || r.includes("spike") || r.includes("revert")) return "Sudden jump not confirmed by the next reading (likely motion or contact artifact). Please check the wearable fit.";
  if (r.includes("implausible")) return "Physiologically implausible value. The sensor reading is unreliable. Please check the wearable device.";
  return "Reading classified as unreliable by the Sensor Trust Engine. Please check the wearable device.";
}

function lastWithin(a: LabAnalysis, i: number, pred: (s: LabStep) => boolean): number {
  for (let k = i; k >= 0 && k > i - HOLD; k--) if (pred(a.steps[k])) return k;
  return -1;
}

function Readings({ s, tone }: { s: LabStep; tone?: Partial<Record<VitalKey, "red" | "yellow">> }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {VITALS.map((k) => (
        <div key={k} className={`rounded-xl px-3 py-2 transition-colors duration-300 ${tone?.[k] === "red" ? "bg-red-50 ring-1 ring-red-300" : tone?.[k] === "yellow" ? "bg-amber-50 ring-1 ring-amber-300" : "bg-slate-50"}`}>
          <p className="text-[11px] font-medium uppercase tracking-wide text-navy-500">{VITAL_META[k].short}</p>
          <p className="text-xl font-semibold tabular-nums text-navy-900" data-testid={`sl-${k}`}>
            {s.latest[k] === undefined ? "—" : s.latest[k]!.toFixed(VITAL_META[k].decimals)}<span className="ml-1 text-xs font-medium text-navy-500">{VITAL_META[k].unit}</span>
          </p>
        </div>
      ))}
    </div>
  );
}

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="flex items-start justify-between gap-3 border-t border-slate-100 py-2 text-sm"><span className="text-navy-500">{label}</span><span className="text-right font-medium text-navy-900">{children}</span></div>
);

function FixedCard({ a, m, i }: { a: LabAnalysis; m: SensorMetrics; i: number }) {
  const k = lastWithin(a, i, (s) => s.comparator.alarm);
  const s = a.steps[i];
  const alarm = k >= 0 ? a.steps[k] : null;
  const alerts = m.fixed.episodes.filter((e) => e.index <= i).length;
  const tone = Object.fromEntries((alarm?.comparator.breaches ?? []).map((b) => [b.vital, "red"])) as Partial<Record<VitalKey, "red">>;
  return (
    <section className={`rounded-2xl border-2 bg-white p-5 shadow-sm transition-colors duration-300 ${alarm ? "border-red-400" : "border-slate-200"}`} data-testid="sl-fixed">
      <p className="text-xs font-semibold uppercase tracking-wider text-navy-500">Traditional</p>
      <h3 className="text-lg font-semibold text-navy-900">Fixed-threshold monitoring (demo comparator)</h3>
      <p className="mt-1 text-xs text-navy-500">Each reading checked alone: SpO₂ &lt; 90 %, HR &lt; 50 / &gt; 120, RR &lt; 8 / &gt; 30, T &gt; 39.0 °C. No sensor-quality check.</p>
      <div className="mt-4"><Readings s={s} tone={tone} /></div>
      <div className={`mt-4 rounded-xl px-4 py-3 transition-colors duration-300 ${alarm ? "bg-red-600 text-white" : "bg-emerald-50 text-emerald-900"}`} data-testid="sl-fixed-status">
        <p className="flex items-center gap-2 font-semibold">{alarm ? <><IconAlert width={18} height={18} />CLINICAL ALERT</> : <><IconCheck width={18} height={18} />No clinical alert</>}</p>
        <p className="text-sm opacity-95">{alarm ? `${alarm.comparator.breaches.map((b) => b.text).join(" · ")} (${tPlus(minutesAt(a, k))})` : "No fixed threshold crossed"}</p>
      </div>
      <Row label="Fixed threshold crossed">{alarm ? "Yes" : "No"}</Row>
      <Row label="Clinical alerts generated"><span className="text-lg tabular-nums" data-testid="sl-fixed-count">{alerts}</span></Row>
    </section>
  );
}

function EngineCard({ a, m, i }: { a: LabAnalysis; m: SensorMetrics; i: number }) {
  const s = a.steps[i];
  const k = lastWithin(a, i, (x) => x.engine.suppressedNow.length > 0);
  const flagged = k >= 0 ? a.steps[k].engine.suppressedNow : [];
  const comparatorAlarmed = k >= 0 && lastWithin(a, i, (x) => x.comparator.alarm) >= 0;
  const lvl = s.engine.level;
  const alerts = m.engine.episodes.filter((e) => e.index <= i).length;
  const caught = a.steps.slice(0, i + 1).reduce((n, x) => n + x.engine.suppressedNow.length, 0);
  const tone = Object.fromEntries(flagged.map((x) => [x.vital, "yellow"])) as Partial<Record<VitalKey, "yellow">>;
  return (
    <section className={`rounded-2xl border-2 bg-white p-5 shadow-sm transition-colors duration-300 ${lvl === "URGENT" ? "border-red-500" : lvl === "REVIEW" ? "border-orange-400" : lvl === "WATCH" ? "border-amber-400" : flagged.length ? "border-amber-300" : "border-emerald-300"}`} data-testid="sl-engine">
      <p className="text-xs font-semibold uppercase tracking-wider text-teal-700">AROGYA DRISHTI</p>
      <h3 className="text-lg font-semibold text-navy-900">Sensor Trust Engine + personalized risk engine</h3>
      <p className="mt-1 text-xs text-navy-500">Same readings. Unreliable readings are classified first; clinical alerts come from the existing risk engine.</p>
      <div className="mt-4"><Readings s={s} tone={tone} /></div>
      <div className={`mt-4 rounded-xl px-4 py-3 transition-colors duration-300 ${lvl === "URGENT" ? "bg-red-600 text-white" : lvl === "REVIEW" ? "bg-orange-500 text-white" : lvl === "WATCH" ? "bg-amber-100 text-amber-950" : "bg-emerald-50 text-emerald-900"}`} data-testid="sl-engine-status">
        <p className="flex items-center gap-2 font-semibold">{lvl === "NORMAL" ? <><IconCheck width={18} height={18} />No clinical alert</> : <><IconAlert width={18} height={18} />CLINICAL ALERT · {lvl}</>}</p>
        <p className="text-sm opacity-95">{lvl === "NORMAL" ? "Reliable readings within the patient's expected range" : s.engine.alerts.slice(0, 2).map((x) => x.reason).join(" ")}</p>
      </div>
      {flagged.length > 0 && (
        <div className="mt-3 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-950 ring-1 ring-amber-300" data-testid="sl-sensor-warning">
          <p className="flex items-center gap-2 font-semibold"><IconShield width={18} height={18} />Sensor-quality warning ({tPlus(minutesAt(a, k))})</p>
          <p className="mt-1">{sensorMessage(flagged[0].vital, flagged[0].reason)}</p>
          <p className="mt-1 text-xs">Detected: {flagged.map((x) => `${VITAL_META[x.vital].short} ${x.value} (${x.reason})`).join("; ")}</p>
        </div>
      )}
      <Row label="Sensor reliability">{flagged.length ? <span className="text-amber-700" data-testid="sl-reliability">Unreliable reading detected</span> : <span className="text-emerald-700" data-testid="sl-reliability">Reliable</span>}</Row>
      <Row label="Clinical alert suppressed">{flagged.length && comparatorAlarmed && lvl === "NORMAL"
        ? <span data-testid="sl-suppressed">Yes: the faulty reading did not raise a clinical alert</span>
        : flagged.length ? <span data-testid="sl-suppressed">Faulty reading excluded from scoring</span> : <span data-testid="sl-suppressed">Not applicable</span>}</Row>
      <Row label="Faulty readings detected so far">{caught}</Row>
      <Row label="Clinical alerts generated"><span className="text-lg tabular-nums" data-testid="sl-engine-count">{alerts}</span></Row>
    </section>
  );
}

function ReliabilityChart({ a, i, vital, limit }: { a: LabAnalysis; i: number; vital: VitalKey; limit: { low?: number; high?: number } }) {
  const flagged = useMemo(() => new Set(a.artifacts.suppressed.filter((x) => x.vital === vital).map((x) => Date.parse(x.effective))), [a, vital]);
  const data = a.steps.slice(0, i + 1).map((s, k) => {
    const ts = Date.parse(s.t);
    return { m: Math.round(minutesAt(a, k) * 10) / 10, v: s.latest[vital], fixedAlert: s.comparator.breaches.some((b) => b.vital === vital), sensor: s.readings[vital] !== undefined && flagged.has(ts) };
  });
  const engineAlerts = a.steps.slice(0, i + 1).map((s, k) => ({ k, s })).filter(({ k, s }) => s.engine.level !== "NORMAL" && !(k > 0 && a.steps[k - 1].engine.level !== "NORMAL"));
  const total = minutesAt(a, a.steps.length - 1);
  const domain: [number, number] = vital === "spo2" ? [0, 100] : [0, 200];
  const Dot = (p: any) => {
    const d = p.payload;
    if (p.cx === undefined || p.cy === undefined) return <g />;
    if (d.sensor) return <circle cx={p.cx} cy={p.cy} r={6} fill="#facc15" stroke={d.fixedAlert ? "#dc2626" : "#a16207"} strokeWidth={2.5} />;
    if (d.fixedAlert) return <circle cx={p.cx} cy={p.cy} r={5} fill="#dc2626" stroke="#fff" strokeWidth={1} />;
    return <circle cx={p.cx} cy={p.cy} r={2} fill="#16a34a" />;
  };
  return (
    <div className="min-w-0 rounded-xl border border-slate-100 bg-slate-50/60 p-3" data-testid={`sl-chart-${vital}`}>
      <p className="mb-1 text-sm font-medium text-navy-900">{VITAL_META[vital].label} <span className="text-xs font-normal text-navy-500">({VITAL_META[vital].unit}, simulated minutes)</span></p>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 16, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="m" type="number" domain={[0, Math.ceil(total)]} tick={{ fontSize: 10, fill: "#47607c" }} />
            <YAxis domain={domain} tick={{ fontSize: 10, fill: "#47607c" }} width={34} />
            {limit.low !== undefined && <ReferenceLine y={limit.low} stroke="#dc2626" strokeDasharray="5 4" label={{ value: `Fixed limit ${limit.low}`, position: "insideBottomRight", fontSize: 10, fill: "#b91c1c" }} />}
            {limit.high !== undefined && <ReferenceLine y={limit.high} stroke="#dc2626" strokeDasharray="5 4" label={{ value: `Fixed limit ${limit.high}`, position: "insideTopRight", fontSize: 10, fill: "#b91c1c" }} />}
            {engineAlerts.map(({ k, s }) => <ReferenceLine key={k} x={Math.round(minutesAt(a, k) * 10) / 10} stroke="#dc2626" strokeWidth={2} label={{ value: `AROGYA ${s.engine.level}`, position: "top", fontSize: 10, fill: "#b91c1c" }} />)}
            <Tooltip labelFormatter={(m) => tPlus(Number(m))} formatter={(v) => [`${v} ${VITAL_META[vital].unit}`, VITAL_META[vital].short]} />
            <Line type="monotone" dataKey="v" stroke="#94a3b8" strokeWidth={1.5} dot={<Dot />} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Results({ m, mode }: { m: SensorMetrics; mode: Mode }) {
  const f = m.fixed, e = m.engine;
  const genuine = (g: SensorMetrics["fixed"]["genuineDeterioration"]) =>
    !g.applicable ? "Not applicable (no deterioration in this scenario)" : g.detected ? `Yes, at ${tPlus(g.minutes ?? 0)}${g.level ? ` (${g.level})` : ""}` : "No";
  const rows: [string, React.ReactNode, React.ReactNode][] = [
    ["Clinical alerts generated", f.clinicalAlerts, <>{e.clinicalAlerts}{e.clinicalAlerts > 0 && e.peakLevel ? <span className="ml-2"><LevelBadge level={e.peakLevel} /></span> : null}</>],
    ["False clinical alerts", f.falseClinicalAlerts, e.falseClinicalAlerts],
    ["Sensor artifacts detected", "Not available (no sensor-quality check)", `${e.artifactsDetected} of ${m.labelledArtifactReadings} labelled faulty readings`],
    ["Genuine deterioration detected", genuine(f.genuineDeterioration), genuine(e.genuineDeterioration)],
  ];
  return (
    <section className="rounded-2xl bg-navy-900 p-6 text-white shadow-lg" data-testid="sl-results">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-300">False alert prevention results</p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead><tr className="text-slate-300"><th className="py-2 pr-4 font-medium">Metric</th><th className="py-2 pr-4 font-medium">Fixed threshold</th><th className="py-2 font-medium">AROGYA DRISHTI</th></tr></thead>
          <tbody>{rows.map(([label, a, b]) => (
            <tr key={label} className="border-t border-white/10" data-testid="sl-row"><td className="py-2.5 pr-4 text-slate-300">{label}</td><td className="py-2.5 pr-4 font-semibold">{a}</td><td className="py-2.5 font-semibold text-teal-200">{b}</td></tr>
          ))}</tbody>
        </table>
      </div>
      {m.falseAlertsAvoided > 0 && (
        <p className="mt-4 rounded-xl bg-teal-600 px-4 py-3 text-lg font-semibold" data-testid="sl-avoided">{m.falseAlertsAvoided} false clinical alert{m.falseAlertsAvoided === 1 ? "" : "s"} avoided in this scenario</p>
      )}
      {mode === "deterioration" && e.genuineDeterioration.detected && (
        <p className="mt-4 rounded-xl bg-white/10 px-4 py-3 text-sm" data-testid="sl-genuine-note">Readings were valid ({e.artifactsDetected} classified as faulty), so the clinical alerts were raised, not suppressed: AROGYA DRISHTI reached {e.peakLevel}.</p>
      )}
      {(e.readingsFlaggedNotLabelled ?? 0) > 0 && <p className="mt-2 text-sm text-amber-200">{e.readingsFlaggedNotLabelled} reading(s) were flagged as faulty although the scenario does not label them as faults.</p>}
      <details className="mt-4 text-xs text-slate-300"><summary className="cursor-pointer">How these numbers are calculated</summary><p className="mt-2 whitespace-pre-line">{m.definitions}</p>
        <p className="mt-1">Counts come from the replayed readings stored in HAPI FHIR and the scenario's ground-truth labels, read after detection. One seeded scenario; not a clinical study.</p></details>
    </section>
  );
}

export function SensorReliabilityLab() {
  const [list, setList] = useState<{ id: string; name: string; source?: string }[]>([]);
  const [pid, setPid] = useState("");
  const [mode, setMode] = useState<Mode>("fault");
  const [runId, setRunId] = useState<string | null>(null);
  const [prep, setPrep] = useState<number | null>(null);
  const [data, setData] = useState<{ a: LabAnalysis; m: SensorMetrics; mode: Mode } | null>(null);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => { fetchPatientList().then((r) => setList(r.patients)).catch((e) => setErr(String(e?.message ?? e))); }, []);
  const patients = useMemo(() => list.filter((p) => !p.source || p.source === "synthea").sort((x, y) => displayName(x.name).localeCompare(displayName(y.name))), [list]);
  useEffect(() => { if (!pid && patients.length) setPid((patients.find((p) => /alex/i.test(p.name)) ?? patients[0]).id); }, [patients, pid]);

  useEffect(() => {
    if (!runId) return;
    let alive = true, t: number | undefined;
    const runMode = mode;
    const tick = async () => {
      try {
        const r = await fetchSensorLabRun(runId);
        if (!alive) return;
        if (r.ready && r.analysis && r.metrics) { setPrep(null); setData({ a: r.analysis, m: r.metrics, mode: runMode }); setI(0); setPlaying(true); return; }
        if (r.session.state === "error" || r.session.state === "stopped") { setErr(r.session.lastError ?? `Run ${r.session.state}`); setPrep(null); return; }
        setPrep(r.session.progress);
        t = window.setTimeout(tick, 1500);
      } catch (e: any) { if (alive) { setErr(String(e?.message ?? e)); setPrep(null); } }
    };
    void tick();
    return () => { alive = false; window.clearTimeout(t); };
  }, [runId, nonce]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!data || !playing) return;
    if (i >= data.a.steps.length - 1) { setPlaying(false); return; }
    const t = window.setTimeout(() => setI((n) => n + 1), STEP_MS[data.mode]);
    return () => window.clearTimeout(t);
  }, [data, i, playing]);

  const run = async () => {
    setErr(null); setData(null); setI(0); setPlaying(false);
    try {
      const prepared = await fetchLabPrepared(pid).catch(() => ({} as Awaited<ReturnType<typeof fetchLabPrepared>>));
      const ready = prepared[SCENARIO[mode]];
      if (ready && ready.state !== "error" && ready.state !== "stopped") { setRunId(ready.runId); setNonce((n) => n + 1); return; }
      setPrep(0);
      setRunId((await startLabRun(pid, SCENARIO[mode])).runId); setNonce((n) => n + 1);
    } catch (e: any) { setErr(String(e?.message ?? e)); setPrep(null); }
  };
  const a = data?.a, m = data?.m;
  const done = !!a && i >= a.steps.length - 1;

  return (
    <div className="space-y-6" data-testid="sensor-lab">
      <section className="rounded-2xl bg-gradient-to-br from-navy-900 to-navy-700 p-6 text-white shadow-sm">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-teal-300"><IconShield width={16} height={16} />Sensor Reliability Lab</p>
        <h2 className="mt-1 text-2xl font-semibold">Traditional vs AROGYA DRISHTI</h2>
        <p className="mt-2 max-w-3xl text-sm text-slate-200">A seeded synthetic scenario from the existing virtual wearable is replayed into HAPI FHIR; both systems then process exactly the same stored readings.</p>
        <div className="mt-5 flex flex-wrap items-end gap-4">
          <label className="text-xs text-slate-300">Patient (synthetic)
            <select value={pid} onChange={(e) => { setPid(e.target.value); setData(null); setRunId(null); }} disabled={prep !== null} data-testid="sl-patient"
              className="mt-1 block w-60 rounded-lg border-0 bg-white/10 px-3 py-2 text-sm text-white">
              {patients.length === 0 && <option value="" className="text-navy-900">Loading patients…</option>}
              {patients.map((p) => <option key={p.id} value={p.id} className="text-navy-900">{displayName(p.name)}</option>)}
            </select></label>
          <div role="radiogroup" aria-label="Scenario" className="flex rounded-lg bg-white/10 p-1">
            {([["fault", "Sensor Fault"], ["deterioration", "Genuine Deterioration"]] as const).map(([id, label]) => (
              <button key={id} type="button" role="radio" aria-checked={mode === id} disabled={prep !== null} onClick={() => { setMode(id); setData(null); setRunId(null); }}
                data-testid={`sl-mode-${id}`} className={`rounded-md px-4 py-2 text-sm font-semibold ${mode === id ? "bg-white text-navy-900" : "text-white hover:bg-white/10"}`}>{label}</button>
            ))}
          </div>
          <button type="button" disabled={!pid || prep !== null} onClick={run} data-testid="sl-run"
            className="inline-flex items-center gap-2 rounded-lg bg-teal-500 px-5 py-2.5 text-sm font-semibold text-white shadow hover:bg-teal-400 disabled:opacity-50">Run False Alert Comparison</button>
          {a && <>
            <button type="button" onClick={() => setPlaying(!playing)} disabled={done} className="rounded-lg px-3 py-2 text-sm font-semibold ring-1 ring-white/30 hover:bg-white/10 disabled:opacity-40">{playing ? "Pause" : "Play"}</button>
            <button type="button" onClick={() => { setI(a.steps.length - 1); setPlaying(false); }} data-testid="sl-skip" className="rounded-lg px-3 py-2 text-sm font-semibold ring-1 ring-white/30 hover:bg-white/10">Skip to results</button>
          </>}
        </div>
        <p className="mt-3 text-xs text-slate-300">{mode === "fault"
          ? "Sensor Fault: stable patient; the wearable produces probe-off zeros (SpO₂ and heart rate 0), motion spikes and an implausible temperature."
          : "Genuine Deterioration: valid readings that worsen progressively (existing deterioration scenario)."} First run per patient and scenario writes about 480 readings to FHIR; afterwards it starts instantly.</p>
      </section>

      {err && <ErrorNote>{err}</ErrorNote>}
      {prep !== null && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" role="status" data-testid="sl-preparing">
          <p className="text-sm font-medium text-navy-900">Writing the scenario readings to HAPI FHIR…</p>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-teal-600 transition-all" style={{ width: `${Math.max(4, prep * 100)}%` }} /></div>
        </div>
      )}

      {a && m && data && (
        <>
          <p className="text-sm text-navy-700">{data.mode === "fault" ? "Sensor Fault" : "Genuine Deterioration"} · simulated time {tPlus(minutesAt(a, i))} of {tPlus(minutesAt(a, a.steps.length - 1))}</p>
          <div className="grid gap-5 lg:grid-cols-2">
            <FixedCard a={a} m={m} i={i} />
            <EngineCard a={a} m={m} i={i} />
          </div>
          <div className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:grid-cols-2">
            <div className="flex flex-wrap items-center gap-4 text-xs text-navy-700 lg:col-span-2">
              <span className="font-semibold text-navy-900">Incoming readings</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-green-600" />Reliable reading</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-full bg-red-600" />Fixed-threshold clinical alert</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-full border-2 border-red-600 bg-yellow-400" />AROGYA sensor-quality warning (faulty reading)</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-3 w-0.5 bg-red-600" />AROGYA clinical alert</span>
            </div>
            <ReliabilityChart a={a} i={i} vital="spo2" limit={{ low: 90 }} />
            <ReliabilityChart a={a} i={i} vital="heart_rate" limit={{ low: 50, high: 120 }} />
          </div>
          {done && <Results m={m} mode={data.mode} />}
        </>
      )}
      <p className="text-xs text-navy-500" data-testid="sl-disclaimer">{BRAND.disclaimer} Synthetic patient and simulated wearable readings; not clinically validated. The fixed-threshold side is a simple demonstration comparator.</p>
    </div>
  );
}
