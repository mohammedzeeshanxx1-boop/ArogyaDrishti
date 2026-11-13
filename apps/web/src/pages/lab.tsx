import { useEffect, useMemo, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  fetchLabPrepared, fetchLabRun, fetchPatientList, startLabRun,
  type Alert, type LabAnalysis, type LabScenario, type LabStep, type VitalKey,
} from "../api";
import { BRAND } from "../brand";
import { IconAlert, IconFlask, IconShield } from "../components/icons";
import { LEVEL_MESSAGE, plainReason } from "../components/risk";
import { ErrorNote, LevelBadge, VITAL_META, displayName } from "../components/ui";


const STEP_MS: Record<LabScenario, number> = { deterioration: 450, artifact: 330 };   // ~55 s and ~40 s of playback
const CARD_VITALS: VitalKey[] = ["spo2", "heart_rate", "respiratory_rate", "body_temperature"];
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const tPlus = (m: number) => `T+${Math.round(m)} min`;
const minutesAt = (a: LabAnalysis, i: number) => (Date.parse(a.steps[i].t) - Date.parse(a.start)) / 60000;
const HOLD = 4;   // keep a momentary alarm / sensor warning on screen for a few playback steps
function lastIndex(a: LabAnalysis, i: number, pred: (s: LabStep) => boolean): number {
  for (let k = i; k >= 0 && k > i - HOLD; k--) if (pred(a.steps[k])) return k;
  return -1;
}
const countUpTo = (a: LabAnalysis, i: number, pred: (s: LabStep) => boolean) => a.steps.slice(0, i + 1).filter(pred).length;
const fmt = (k: VitalKey, v: number | undefined) => (v === undefined ? "—" : v.toFixed(VITAL_META[k].decimals));

function Vitals({ step, highlight }: { step: LabStep; highlight?: Set<string> }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {CARD_VITALS.map((k) => {
        const hot = highlight?.has(k);
        return (
          <div key={k} className={`rounded-xl px-3 py-2 transition-colors duration-500 ${hot ? "bg-red-50 ring-1 ring-red-300" : "bg-slate-50"}`}>
            <p className="text-[11px] font-medium uppercase tracking-wide text-navy-500">{VITAL_META[k].short}</p>
            <p className="text-xl font-semibold tabular-nums text-navy-900" data-testid={`lab-${k}`}>{fmt(k, step.latest[k])}<span className="ml-1 text-xs font-medium text-navy-500">{VITAL_META[k].unit}</span></p>
          </div>
        );
      })}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex items-start justify-between gap-3 border-t border-slate-100 py-2 text-sm"><span className="text-navy-500">{label}</span><span className="text-right font-medium text-navy-900">{children}</span></div>;
}

function TraditionalCard({ a, i, done }: { a: LabAnalysis; i: number; done: boolean }) {
  const s = a.steps[i];
  const fc = a.firstComparatorAlert;
  const raised = fc && i >= fc.index;
  const k = lastIndex(a, i, (x) => x.comparator.alarm);
  const alarmNow = k >= 0;
  const shown = alarmNow ? a.steps[k] : s;
  const alarms = countUpTo(a, i, (x) => x.comparator.alarm);
  return (
    <section className={`flex flex-col rounded-2xl border-2 bg-white p-5 shadow-sm transition-colors duration-500 ${alarmNow ? "border-red-400" : raised ? "border-red-200" : "border-slate-200"}`} data-testid="lab-traditional">
      <p className="text-xs font-semibold uppercase tracking-wider text-navy-500">Traditional monitoring</p>
      <h3 className="text-lg font-semibold text-navy-900">{a.comparator.name}</h3>
      <p className="mt-1 text-xs text-navy-500">Fixed alarm limits on each reading: SpO₂ &lt; 90 %, HR &lt; 50 / &gt; 120, RR &lt; 8 / &gt; 30, T &gt; 39.0 °C</p>
      <div className="mt-4"><Vitals step={s} highlight={new Set(shown.comparator.breaches.map((b) => b.vital))} /></div>
      <div className={`mt-4 rounded-xl px-4 py-3 transition-colors duration-500 ${alarmNow ? "bg-red-600 text-white" : "bg-slate-100 text-navy-900"}`} data-testid="lab-traditional-status">
        <p className="font-semibold">{alarmNow ? "ALARM" : raised ? "No alarm on this reading" : "No alarm"}</p>
        <p className="text-sm opacity-90">{alarmNow ? `${shown.comparator.breaches.map((b) => b.text).join(" · ")} (at ${tPlus(minutesAt(a, k))})` : "All readings within the fixed limits"}</p>
      </div>
      <div className="mt-3">
        <Row label="First alert">{raised ? <span data-testid="lab-trad-first">{clock(fc!.t)} · {tPlus(fc!.minutesFromStart)}</span> : done ? <span data-testid="lab-trad-first">Not detected</span> : "Not yet"}</Row>
        <Row label="Deterioration detected">{raised ? "Yes" : "No"}</Row>
        <Row label="Alarm moments so far"><span data-testid="lab-trad-count">{alarms}</span></Row>
      </div>
    </section>
  );
}

function EngineCard({ a, i, done }: { a: LabAnalysis; i: number; done: boolean }) {
  const s = a.steps[i];
  const fw = a.firstWarning;
  const ft = a.firstTrendWarning;
  const lvl = s.engine.level;
  const warned = fw && i >= fw.index;
  const trendSeen = ft && i >= ft.index;
  const ks = lastIndex(a, i, (x) => x.engine.suppressedNow.length > 0);
  const sup = ks >= 0 ? a.steps[ks].engine.suppressedNow : [];
  const caught = a.steps.slice(0, i + 1).reduce((n, x) => n + x.engine.suppressedNow.length, 0);
  const tone = lvl === "URGENT" ? "border-red-500" : lvl === "REVIEW" ? "border-orange-400" : lvl === "WATCH" ? "border-amber-400" : "border-teal-300";
  const trend = s.engine.alerts.find((x) => x.ruleType === "personal-baseline");
  return (
    <section className={`flex flex-col rounded-2xl border-2 bg-white p-5 shadow-sm transition-colors duration-500 ${tone}`} data-testid="lab-engine">
      <p className="text-xs font-semibold uppercase tracking-wider text-teal-700">AROGYA DRISHTI</p>
      <h3 className="text-lg font-semibold text-navy-900">Personalized monitoring</h3>
      <p className="mt-1 text-xs text-navy-500">Sensor Trust Engine · partial NEWS2-style score · personal baselines and trend rules</p>
      <div className="mt-4"><Vitals step={s} /></div>
      <div className={`mt-4 rounded-xl px-4 py-3 transition-colors duration-500 ${lvl === "URGENT" ? "bg-red-600 text-white" : lvl === "REVIEW" ? "bg-orange-500 text-white" : lvl === "WATCH" ? "bg-amber-100 text-amber-950" : "bg-teal-50 text-teal-900"}`} data-testid="lab-engine-status">
        <div className="flex items-center gap-2"><span className="font-semibold">{lvl}</span><span className="text-sm opacity-90">· NEWS2-style score {s.engine.news2} (partial, {s.engine.measured} of 7)</span></div>
        <p className="text-sm opacity-95">{lvl === "NORMAL" ? "Readings consistent with this patient's expected range." : LEVEL_MESSAGE[lvl]}</p>
      </div>
      {sup.length > 0 && (
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-sky-50 px-4 py-3 text-sm text-sky-900 ring-1 ring-sky-200" data-testid="lab-sensor-warning">
          <IconShield className="mt-0.5 shrink-0" width={18} height={18} />
          <span><strong>Sensor-quality warning</strong> ({tPlus(minutesAt(a, ks))}): {sup.map((x) => `${VITAL_META[x.vital].short} ${x.value} (${x.reason})`).join("; ")}. Reading excluded; no clinical alert from it.</span>
        </div>
      )}
      <div className="mt-3">
        <Row label="Faulty readings caught so far"><span data-testid="lab-engine-caught">{caught}</span></Row>
        <Row label="Early trend warning">{trend ? <span className="text-amber-800">{plainReason(trend as unknown as Alert)}</span> : trendSeen ? `First at ${tPlus(ft!.minutesFromStart)}` : "None"}</Row>
        <Row label="First warning">{warned ? <span data-testid="lab-engine-first">{clock(fw!.t)} · {tPlus(fw!.minutesFromStart)} · <LevelBadge level={fw!.level ?? null} /></span> : done ? <span data-testid="lab-engine-first">Not detected</span> : "Not yet"}</Row>
        {s.engine.alerts.length > 0 && (
          <div className="border-t border-slate-100 pt-2 text-sm">
            <p className="text-navy-500">Why</p>
            <ul className="mt-1 space-y-1">{s.engine.alerts.slice(0, 4).map((x, k) => <li key={k} className="text-navy-900">• {plainReason(x as unknown as Alert)}</li>)}</ul>
          </div>
        )}
      </div>
    </section>
  );
}

function DetectionChart({ a, i, vital, limit }: { a: LabAnalysis; i: number; vital: VitalKey; limit: number }) {
  const data = useMemo(() => a.steps.slice(0, i + 1).map((s, k) => ({
    m: Math.round(minutesAt(a, k) * 10) / 10, v: s.latest[vital], baseline: vital === "spo2" ? s.spo2Baseline ?? undefined : undefined,
  })), [a, i, vital]);
  const total = minutesAt(a, a.steps.length - 1);
  const fw = a.firstWarning && i >= a.firstWarning.index ? a.firstWarning : null;
  const fc = a.firstComparatorAlert && i >= a.firstComparatorAlert.index ? a.firstComparatorAlert : null;
  const domain: [number, number] = vital === "spo2" ? [80, 100] : [40, 150];
  return (
    <div className="min-w-0 rounded-xl border border-slate-100 bg-slate-50/60 p-3" data-testid={`lab-chart-${vital}`}>
      <p className="mb-1 text-sm font-medium text-navy-900">{VITAL_META[vital].label} <span className="text-xs font-normal text-navy-500">({VITAL_META[vital].unit}, simulated minutes)</span></p>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 18, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="m" type="number" domain={[0, Math.ceil(total)]} tickFormatter={(m) => `${m}`} tick={{ fontSize: 10, fill: "#47607c" }} />
            <YAxis domain={domain} tick={{ fontSize: 10, fill: "#47607c" }} width={34} allowDataOverflow />
            <ReferenceLine y={limit} stroke="#dc2626" strokeDasharray="5 4" label={{ value: `Fixed limit ${limit}`, position: "insideTopRight", fontSize: 10, fill: "#b91c1c" }} />
            {fw && <ReferenceLine x={Math.round(fw.minutesFromStart * 10) / 10} stroke="#0d9488" strokeWidth={2} label={{ value: "AROGYA warning", position: "top", fontSize: 10, fill: "#0f766e" }} />}
            {fc && <ReferenceLine x={Math.round(fc.minutesFromStart * 10) / 10} stroke="#dc2626" strokeWidth={2} label={{ value: "Fixed alarm", position: "top", fontSize: 10, fill: "#b91c1c" }} />}
            <Tooltip labelFormatter={(m) => tPlus(Number(m))} formatter={(v, n) => [`${Number(v).toFixed(VITAL_META[vital].decimals)} ${VITAL_META[vital].unit}`, n === "baseline" ? "Personal baseline" : VITAL_META[vital].short]} />
            {vital === "spo2" && <Line type="stepAfter" dataKey="baseline" stroke="#0d9488" strokeDasharray="4 3" dot={false} isAnimationActive={false} connectNulls />}
            <Line type="monotone" dataKey="v" stroke="#1d4063" strokeWidth={2.4} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Summary({ a }: { a: LabAnalysis }) {
  const fw = a.firstWarning, fc = a.firstComparatorAlert, adv = a.advantageMinutes;
  const reasons = (fw?.alerts ?? []).map((x) => plainReason(x as unknown as Alert));
  const trend = a.firstTrendWarning?.alerts?.find((x) => x.ruleType === "personal-baseline");
  return (
    <section className="rounded-2xl border border-navy-900/10 bg-navy-900 p-6 text-white shadow-lg" data-testid="lab-summary">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-300">Early detection performance</p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div className="rounded-xl bg-white/5 p-4"><p className="text-sm text-slate-300">Traditional (fixed-threshold comparator)</p>
          <p className="mt-1 text-xl font-semibold" data-testid="lab-sum-trad">{fc ? `First alert at ${clock(fc.t)} (${tPlus(fc.minutesFromStart)})` : "Not detected"}</p>
          {fc && <p className="text-xs text-slate-300">{fc.breaches?.map((b) => b.text).join("; ")}</p>}</div>
        <div className="rounded-xl bg-white/5 p-4"><p className="text-sm text-slate-300">AROGYA DRISHTI</p>
          <p className="mt-1 text-xl font-semibold" data-testid="lab-sum-engine">{fw ? `First warning at ${clock(fw.t)} (${tPlus(fw.minutesFromStart)})` : "Not detected"}</p>
          {fw && <p className="text-xs text-slate-300">{fw.level}</p>}</div>
        <div className={`rounded-xl p-4 ${adv !== null && adv > 0 ? "bg-teal-600" : "bg-white/10"}`}><p className="text-sm text-white/80">Detection advantage</p>
          <p className="mt-1 text-2xl font-bold" data-testid="lab-advantage">
            {adv === null ? (fw && !fc ? "Only AROGYA DRISHTI detected it" : !fw && fc ? "Only the comparator alerted" : "No detection by either") :
              adv > 0 ? `${adv} min earlier` : adv === 0 ? "Same time" : `${Math.abs(adv)} min later`}</p>
          <p className="text-xs text-white/80">Measured on the simulated scenario clock</p></div>
      </div>
      {fw && (
        <div className="mt-4 text-sm text-slate-200">
          <p className="font-semibold text-white">Why AROGYA DRISHTI warned</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">{reasons.map((r, k) => <li key={k}>{r}</li>)}
            {trend && <li>Personal-baseline trend at {tPlus(a.firstTrendWarning!.minutesFromStart)}: {plainReason(trend as unknown as Alert)}</li>}</ul>
        </div>
      )}
      <p className="mt-4 text-xs text-slate-400">Both systems read the same {a.steps.length} replayed measurement times stored in HAPI FHIR (seeded synthetic scenario). One scenario is not a clinical study; results depend on the scenario and on the comparator limits shown.</p>
    </section>
  );
}

function ArtifactSummary({ a }: { a: LabAnalysis }) {
  const ar = a.artifacts;
  return (
    <section className="rounded-2xl border border-navy-900/10 bg-navy-900 p-6 text-white shadow-lg" data-testid="lab-artifact-summary">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-300">False alert prevention</p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div className="rounded-xl bg-white/5 p-4"><p className="text-sm text-slate-300">Faulty readings in the stream</p><p className="mt-1 text-3xl font-bold" data-testid="lab-faulty">{ar.suppressed.length}</p><p className="text-xs text-slate-300">probe-off zeros, motion spikes, implausible values</p></div>
        <div className="rounded-xl bg-red-600/90 p-4"><p className="text-sm text-white/80">Fixed-threshold comparator</p><p className="mt-1 text-3xl font-bold" data-testid="lab-false-alarms">{ar.comparatorAlarmsFromArtifacts.length}</p><p className="text-xs text-white/80">alarms triggered by faulty readings ({a.comparatorAlarmSteps} alarm moments in total)</p></div>
        <div className="rounded-xl bg-teal-600 p-4"><p className="text-sm text-white/80">AROGYA DRISHTI clinical alerts</p><p className="mt-1 text-3xl font-bold" data-testid="lab-engine-alerts">{a.engineAlertSteps}</p><p className="text-xs text-white/80">faulty readings flagged as sensor-quality issues instead</p></div>
      </div>
      <ul className="mt-4 grid gap-1 text-sm text-slate-200 md:grid-cols-2">
        {ar.suppressed.slice(0, 10).map((s, k) => <li key={k}>• {VITAL_META[s.vital]?.short} {s.value}: {s.reason}</li>)}
      </ul>
    </section>
  );
}

export function EarlyDetectionLab() {
  const [list, setList] = useState<{ id: string; name: string; source?: string }[]>([]);
  useEffect(() => { fetchPatientList().then((r) => setList(r.patients)).catch((e) => setErr(String(e?.message ?? e))); }, []);
  const patients = useMemo(() => list.filter((p) => !p.source || p.source === "synthea")
    .sort((x, y) => displayName(x.name).localeCompare(displayName(y.name))), [list]);
  const [pid, setPid] = useState("");
  const [mode, setMode] = useState<LabScenario>("deterioration");
  const [runId, setRunId] = useState<string | null>(null);
  const [prep, setPrep] = useState<{ progress: number; persisted: number; total: number } | null>(null);
  const [a, setA] = useState<LabAnalysis | null>(null);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [prepared, setPrepared] = useState<Partial<Record<LabScenario, { runId: string; state: string }>>>({});
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => { if (!pid && patients.length) setPid((patients.find((p) => /alex/i.test(p.name)) ?? patients[0]).id); }, [patients, pid]);
  useEffect(() => { if (pid) fetchLabPrepared(pid).then(setPrepared).catch(() => setPrepared({})); }, [pid, runId]);

  // Wait for the replay to be stored in HAPI, then load the analysis.
  useEffect(() => {
    if (!runId) return;
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetchLabRun(runId);
        if (!alive) return;
        if (r.ready && r.analysis) { setPrep(null); setA(r.analysis); setI(0); setPlaying(true); return; }
        if (r.session.state === "error" || r.session.state === "stopped") { setErr(r.session.lastError ?? `Replay ${r.session.state}`); setPrep(null); return; }
        setPrep({ progress: r.session.progress, persisted: r.session.persisted, total: r.session.eventsTotal });
        timer.current = window.setTimeout(tick, 1500);
      } catch (e: any) { if (alive) { setErr(String(e?.message ?? e)); setPrep(null); } }
    };
    void tick();
    return () => { alive = false; window.clearTimeout(timer.current); };
  }, [runId]);

  // Playback over the real stored steps.
  useEffect(() => {
    if (!a || !playing) return;
    if (i >= a.steps.length - 1) { setPlaying(false); return; }
    const t = window.setTimeout(() => setI((n) => Math.min(n + 1, a.steps.length - 1)), STEP_MS[mode]);
    return () => window.clearTimeout(t);
  }, [a, i, playing, mode]);

  const run = async (scenario: LabScenario, fresh = false) => {
    setErr(null); setA(null); setI(0); setPlaying(false); setMode(scenario);
    const ready = prepared[scenario];
    if (!fresh && ready && ready.state !== "error") { setRunId(null); setTimeout(() => setRunId(ready.runId), 0); return; }
    setPrep({ progress: 0, persisted: 0, total: 0 });
    try { setRunId((await startLabRun(pid, scenario)).runId); } catch (e: any) { setErr(String(e?.message ?? e)); setPrep(null); }
  };
  const done = !!a && i >= a.steps.length - 1;
  const busy = prep !== null;
  const patientName = displayName(patients.find((p) => p.id === pid)?.name ?? "");

  return (
    <div className="space-y-6" data-testid="early-detection-lab">
      <section className="overflow-hidden rounded-2xl bg-gradient-to-br from-navy-900 to-navy-700 p-6 text-white shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-teal-300"><IconFlask width={16} height={16} />Early Detection Lab</p>
            <h2 className="mt-1 text-2xl font-semibold">Traditional vs AROGYA DRISHTI</h2>
            <p className="mt-2 text-sm text-slate-200">A seeded synthetic scenario is replayed into HAPI FHIR on a simulated clock (kept apart from live monitoring, so it creates no live alerts), then both systems read exactly the same stored readings, step by step.</p>
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-xs text-slate-300">Patient (synthetic)
              <select value={pid} onChange={(e) => { setPid(e.target.value); setA(null); setRunId(null); }} disabled={busy} data-testid="lab-patient"
                className="mt-1 block w-64 rounded-lg border-0 bg-white/10 px-3 py-2 text-sm text-white">
                {patients.length === 0 && <option value="" className="text-navy-900">Loading patients…</option>}
                {patients.map((p) => <option key={p.id} value={p.id} className="text-navy-900">{displayName(p.name)}</option>)}
              </select></label>
          </div>
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          <button type="button" disabled={!pid || busy} onClick={() => run("deterioration")} data-testid="lab-run-early"
            className="inline-flex items-center gap-2 rounded-lg bg-teal-500 px-5 py-2.5 text-sm font-semibold text-white shadow hover:bg-teal-400 disabled:opacity-50"><IconAlert width={18} height={18} />Demonstrate Early Detection</button>
          <button type="button" disabled={!pid || busy} onClick={() => run("artifact")} data-testid="lab-run-artifact"
            className="inline-flex items-center gap-2 rounded-lg bg-white/10 px-5 py-2.5 text-sm font-semibold text-white ring-1 ring-white/30 hover:bg-white/20 disabled:opacity-50"><IconShield width={18} height={18} />Demonstrate False Alert Prevention</button>
          {a && <>
            <button type="button" onClick={() => setPlaying(!playing)} disabled={done} className="rounded-lg px-3 py-2 text-sm font-semibold text-white ring-1 ring-white/30 hover:bg-white/10 disabled:opacity-40">{playing ? "Pause" : "Play"}</button>
            <button type="button" onClick={() => { setI(a.steps.length - 1); setPlaying(false); }} data-testid="lab-skip" className="rounded-lg px-3 py-2 text-sm font-semibold text-white ring-1 ring-white/30 hover:bg-white/10">Skip to result</button>
            <button type="button" onClick={() => { setI(0); setPlaying(true); }} className="rounded-lg px-3 py-2 text-sm font-semibold text-white ring-1 ring-white/30 hover:bg-white/10">Replay</button>
          </>}
        </div>
        <p className="mt-3 text-xs text-slate-300" data-testid="lab-prepared">
          {prepared.deterioration?.state === "completed" || prepared.artifact?.state === "completed"
            ? `Prepared for ${patientName}: ${[prepared.deterioration?.state === "completed" && "early detection", prepared.artifact?.state === "completed" && "false alert prevention"].filter(Boolean).join(" and ")} (plays instantly). `
            : "First run for this patient writes about 480 readings to HAPI FHIR (about a minute); later runs play instantly. "}
          {(prepared.deterioration || prepared.artifact) && !busy && <button type="button" className="underline" onClick={() => run(mode, true)}>Regenerate data</button>}
        </p>
      </section>

      {err && <ErrorNote>{err}</ErrorNote>}
      {busy && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" role="status" data-testid="lab-preparing">
          <p className="text-sm font-medium text-navy-900">Writing the {mode === "deterioration" ? "Gradual Deterioration" : "Sensor Artifact"} scenario to HAPI FHIR… {prep!.total ? `${prep!.persisted} of ${prep!.total} readings` : ""}</p>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-teal-600 transition-all" style={{ width: `${Math.max(4, prep!.progress * 100)}%` }} /></div>
        </div>
      )}

      {a && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-navy-700">
            <p><strong>{patientName}</strong> · {mode === "deterioration" ? "Gradual Deterioration" : "Stable with Sensor Artifacts"} · simulated time {clock(a.steps[i].t)} ({tPlus(minutesAt(a, i))} of {tPlus(minutesAt(a, a.steps.length - 1))})</p>
            <div className="h-1.5 w-48 overflow-hidden rounded-full bg-slate-200"><div className="h-full bg-teal-600" style={{ width: `${(100 * i) / (a.steps.length - 1)}%` }} /></div>
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <TraditionalCard a={a} i={i} done={done} />
            <EngineCard a={a} i={i} done={done} />
          </div>
          <div className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:grid-cols-2">
            <div className="lg:col-span-2 flex flex-wrap items-center gap-4 text-xs text-navy-700">
              <span className="font-semibold text-navy-900">Detection timeline</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-5 bg-teal-600" />AROGYA DRISHTI first warning</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-5 bg-red-600" />Fixed-threshold first alarm</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-5 border-t-2 border-dashed border-teal-600" />Personal SpO₂ baseline</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-5 border-t-2 border-dashed border-red-600" />Fixed limit</span>
            </div>
            <DetectionChart a={a} i={i} vital="spo2" limit={90} />
            <DetectionChart a={a} i={i} vital="heart_rate" limit={120} />
          </div>
          {done && (mode === "deterioration" ? <Summary a={a} /> : <ArtifactSummary a={a} />)}
          <details className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-navy-700">
            <summary className="cursor-pointer font-semibold text-navy-900">How the two sides are computed</summary>
            <p className="mt-2"><strong>{a.comparator.name}:</strong> {a.comparator.description}</p>
            <p className="mt-1"><strong>{a.engine.name}:</strong> {a.engine.description}</p>
          </details>
        </>
      )}
      <p className="text-xs text-navy-500" data-testid="lab-disclaimer">{BRAND.disclaimer} Synthetic patient and simulated readings; not clinically validated. The comparator is a simple fixed-threshold demonstration, not a model of all traditional monitoring.</p>
    </div>
  );
}

export function LabPromo() {
  return (
    <a href="#/doctor/lab" className="group flex items-center justify-between gap-4 rounded-2xl bg-gradient-to-r from-navy-900 to-navy-700 p-5 text-white shadow-sm" data-testid="lab-promo">
      <span><span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-teal-300"><IconFlask width={16} height={16} />Early Detection Lab</span>
        <span className="mt-1 block text-lg font-semibold">Traditional vs AROGYA DRISHTI on the same readings</span>
        <span className="block text-sm text-slate-300">Run a deterioration or a sensor-fault scenario and compare when each system alerts.</span></span>
      <span className="rounded-lg bg-teal-500 px-4 py-2 text-sm font-semibold group-hover:bg-teal-400">Open lab</span>
    </a>
  );
}

