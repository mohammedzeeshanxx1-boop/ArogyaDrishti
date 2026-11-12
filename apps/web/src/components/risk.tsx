import type { Alert, Monitor, RiskLevel, VitalKey } from "../api";
import { LevelBadge, VITAL_META, fmtDateTime, fmtTime } from "./ui";

const HEADLINE: Record<RiskLevel, string> = {
  NORMAL: "Readings are within the expected ranges. The monitoring rules indicate no action.",
  WATCH: "Early changes detected. Continue monitoring; consider checking in with the patient.",
  REVIEW: "Clinically relevant changes. The monitoring rules recommend clinician review.",
  URGENT: "Marked changes across vital signs. The monitoring rules flag this patient for urgent clinical review.",
};

const fmtVal = (a: Alert) => (a.vital ? `${Number(a.value).toFixed(VITAL_META[a.vital].decimals)} ${VITAL_META[a.vital].unit}` : String(a.value));

/** One plain-language sentence per triggered rule (the technical wording stays in the details section). */
export function plainReason(a: Alert): string {
  if (a.ruleType === "news2-aggregate") return `Combined early-warning score ${a.value} (partial: 4 of 7 measures available).`;
  if (!a.vital) return a.reason;
  const name = VITAL_META[a.vital].short;
  if (a.ruleType === "personal-baseline" && a.baseline) {
    const dir = Number(a.value) > a.baseline.median ? "higher" : "lower";
    return `${name} ${fmtVal(a)} is ${dir} than this patient's usual ${a.baseline.median.toFixed(VITAL_META[a.vital].decimals)} ${VITAL_META[a.vital].unit}.`;
  }
  return `${name} ${fmtVal(a)} is outside the expected range${a.score ? ` (adds ${a.score} point${a.score === 1 ? "" : "s"})` : ""}.`;
}

export function notAssessedText(m: Monitor): string {
  const a = m.assessment;
  return a.monitoringStatus === "no_recent_data"
    ? `No readings received in the last ${a.recentWindowMinutes} minutes, so risk is not assessed.`
    : `Not enough trusted readings to assess risk: ${a.trustedVitals} of ${a.requiredTrustedVitals} vital signs available.`;
}

export function RiskPanel({ monitor, waiting }: { monitor: Monitor | null; waiting: boolean }) {
  if (!monitor || waiting) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-navy-900">Risk assessment</h2>
        <div className="mt-3" data-testid="risk-not-assessed"><LevelBadge level={null} large />
          <p className="mt-2 text-sm text-navy-700">{waiting ? "Not assessed: waiting for readings from the new run." : "Loading monitoring data…"}</p></div>
      </section>
    );
  }
  const a = monitor.assessment;
  const r = monitor.risk;
  const reasons = r.alerts.filter((x) => x.level !== "NORMAL");
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="risk-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-navy-900">Risk assessment</h2>
        <span className="text-xs text-navy-500">Assessed {fmtTime(monitor.evaluatedAt)}</span>
      </div>
      {!a.assessable ? (
        <div className="mt-3" data-testid="risk-not-assessed">
          <LevelBadge level={null} large />
          <p className="mt-2 text-sm text-navy-700">{notAssessedText(monitor)}</p>
        </div>
      ) : (
        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-3">
            <span data-testid="risk-level"><LevelBadge level={r.level} large /></span>
            <p className="max-w-xl text-sm font-medium text-navy-900" data-testid="risk-headline">{HEADLINE[r.level]}</p>
          </div>
          {reasons.length > 0 && (
            <div className="mt-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-navy-500">Why</p>
              <ul className="mt-1.5 space-y-1.5" data-testid="risk-reasons">
                {reasons.map((x, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-navy-900">
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${x.level === "URGENT" ? "bg-red-600" : x.level === "REVIEW" ? "bg-orange-600" : "bg-amber-500"}`} aria-hidden />
                    {plainReason(x)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      <p className="mt-4 text-xs text-navy-500" data-testid="reliability">
        Based on {a.trustedVitals} of 4 vital signs with trusted recent readings · {r.suppressedCount} reading{r.suppressedCount === 1 ? "" : "s"} excluded as likely sensor artifacts ·{" "}
        {a.monitoringStatus === "stale" ? "data is stale" : a.monitoringStatus === "active" ? "data is current" : "no current data"}. Partial NEWS2-style scoring; decision support only, not clinically validated.
      </p>
      <TechnicalDetails monitor={monitor} />
    </section>
  );
}

function TechnicalDetails({ monitor }: { monitor: Monitor }) {
  const r = monitor.risk;
  const p = r.news2.parameters;
  return (
    <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-navy-700" data-testid="technical-details">
      <summary className="cursor-pointer select-none text-sm font-semibold text-navy-900">Technical details</summary>
      <div className="mt-3 space-y-3">
        <p>Partial NEWS2-style total <strong>{r.news2.total}</strong> from {r.news2.measuredParameters} of {r.news2.of} parameters (SpO₂ Scale {r.news2.spo2Scale}). Not measured: {r.news2.notAvailable.join(", ")}. {r.label}</p>
        <table className="w-full text-left">
          <thead className="text-navy-500"><tr><th className="py-1 pr-2 font-medium">Vital</th><th className="pr-2 font-medium">Value</th><th className="pr-2 font-medium">Score</th><th className="pr-2 font-medium">Bands</th><th className="font-medium">Observation</th></tr></thead>
          <tbody>
            {(Object.keys(p) as VitalKey[]).map((k) => (
              <tr key={k} className="border-t border-slate-200 align-top">
                <td className="py-1 pr-2">{VITAL_META[k].short}</td><td className="pr-2 tabular-nums">{p[k]!.value}</td><td className="pr-2">{p[k]!.score}</td>
                <td className="pr-2">{p[k]!.bands}</td><td className="font-mono">{p[k]!.observation}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {r.alerts.length > 0 && (
          <div><p className="font-semibold text-navy-900">Rules evaluated</p>
            <ul className="mt-1 space-y-1">{r.alerts.map((x, i) => <li key={i}><span className="font-semibold">{x.level}</span> · {x.ruleType} · {x.reason} <span className="text-navy-500">Rule: {x.rule}</span></li>)}</ul></div>
        )}
        {r.suppressed.length > 0 && (
          <div><p className="font-semibold text-navy-900">Excluded readings (Sensor Trust Engine)</p>
            <ul className="mt-1 space-y-0.5">{r.suppressed.slice(-8).reverse().map((s, i) => <li key={i}>{VITAL_META[s.vital]?.short ?? s.vital} {s.value} at {fmtTime(s.effective)}: {s.reason} <span className="font-mono">{s.observation}</span></li>)}</ul></div>
        )}
        {monitor.fhirProof && (
          <p>Latest stored resource: <span className="font-mono">{monitor.fhirProof.observation}</span> (version {monitor.fhirProof.versionId}, stored {fmtDateTime(monitor.fhirProof.lastUpdated)}){monitor.fhirProof.readBackMatches !== null ? `, read-back match: ${monitor.fhirProof.readBackMatches ? "yes" : "no"}` : ""}.</p>
        )}
        <p>Window: readings since {fmtDateTime(monitor.windowStart)} · {monitor.observationCount} observations · sources: {monitor.assessment.sources?.join(", ") || "none"}.</p>
      </div>
    </details>
  );
}

/** Wording for the Patient Portal: plain, non-diagnostic, points to the care team. */
export function patientStatus(m: Monitor | null): { title: string; body: string; tone: "ok" | "info" | "warn" | "alert" | "muted" } {
  if (!m) return { title: "Loading your latest readings…", body: "", tone: "muted" };
  const a = m.assessment;
  if (!a.assessable || !a.level) {
    return a.monitoringStatus === "no_recent_data"
      ? { title: "No recent readings", body: "We have not received readings from your monitoring device recently, so there is no current update.", tone: "muted" }
      : { title: "Not enough readings yet", body: "There are not enough recent readings to give an update. This will update automatically as readings arrive.", tone: "muted" };
  }
  switch (a.level) {
    case "NORMAL": return { title: "Your readings look steady", body: "Your recent readings are within the expected ranges.", tone: "ok" };
    case "WATCH": return { title: "Some readings have changed", body: "Some of your recent readings have changed. Your care team can see these readings on their dashboard.", tone: "info" };
    case "REVIEW": return { title: "Your care team will review your readings", body: "Some of your readings are flagged for review on your care team's dashboard.", tone: "warn" };
    default: return { title: "Your readings are flagged as urgent", body: "Your readings are flagged as urgent on your care team's dashboard. If you feel unwell, contact your care team now or call your local emergency number.", tone: "alert" };
  }
}

