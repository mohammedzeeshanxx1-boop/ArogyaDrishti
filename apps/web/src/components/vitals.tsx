import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Monitor, VitalKey } from "../api";
import { IconDown, IconDrop, IconFlat, IconHeart, IconThermo, IconUp, IconWind } from "./icons";
import { LevelBadge, VITAL_META, ago, fmtDateTime, fmtTime } from "./ui";

export const ORDER: VitalKey[] = ["heart_rate", "spo2", "respiratory_rate", "body_temperature"];
const ICON = { heart_rate: IconHeart, spo2: IconDrop, respiratory_rate: IconWind, body_temperature: IconThermo } as const;
const TINT = { heart_rate: "bg-rose-50 text-rose-700", spo2: "bg-sky-50 text-sky-700", respiratory_rate: "bg-teal-50 text-teal-700", body_temperature: "bg-amber-50 text-amber-700" } as const;
const DOMAIN: Record<VitalKey, [number, number]> = { heart_rate: [40, 150], spo2: [80, 100], respiratory_rate: [6, 36], body_temperature: [35, 40] };

/** Readings the risk engine trusted (likely sensor artifacts removed), oldest first. */
export function trustedSeries(m: Monitor, k: VitalKey) {
  const excluded = new Set(m.risk.suppressed.map((s) => s.observation));
  return m.vitals[k].series.filter((p) => !excluded.has(p.observation)).map((p) => ({ ...p, ts: Date.parse(p.effective) }));
}

export type Trend = "rising" | "falling" | "steady" | null;
/** Latest value against the mean of the previous (up to 5) trusted readings; null when fewer than 4 readings. */
export function trendOf(m: Monitor, k: VitalKey): Trend {
  const s = trustedSeries(m, k);
  if (s.length < 4) return null;
  const prev = s.slice(-6, -1);
  const mean = prev.reduce((a, p) => a + p.value, 0) / prev.length;
  const d = s[s.length - 1].value - mean;
  return Math.abs(d) < VITAL_META[k].step ? "steady" : d > 0 ? "rising" : "falling";
}

function TrendChip({ trend }: { trend: Trend }) {
  if (!trend) return <span className="text-xs text-navy-500">Trend: not enough readings yet</span>;
  const [Icon, text] = trend === "rising" ? [IconUp, "Rising"] : trend === "falling" ? [IconDown, "Falling"] : [IconFlat, "Steady"];
  return <span className="inline-flex items-center gap-1 text-xs font-medium text-navy-700" data-testid="trend"><Icon width={14} height={14} />{text}</span>;
}

export function VitalCard({ k, monitor, waiting = false, clinician = false }: { k: VitalKey; monitor: Monitor | null; waiting?: boolean; clinician?: boolean }) {
  const meta = VITAL_META[k];
  const Icon = ICON[k];
  const trusted = monitor && !waiting ? monitor.risk.news2.parameters[k] : undefined;
  const staleMin = monitor?.assessment.staleAfterMinutes ?? 15;
  const isStale = trusted ? Date.now() - Date.parse(trusted.effective) > staleMin * 60000 : false;
  const alert = clinician && monitor?.assessment.assessable && !waiting ? monitor.risk.alerts.find((a) => a.vital === k && a.level !== "NORMAL") : undefined;
  const b = trusted?.baseline;
  return (
    <div data-testid={`vital-${k}`} className={`min-w-0 rounded-2xl border bg-white p-5 shadow-sm transition-colors ${isStale ? "border-amber-300" : "border-slate-200"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className={`grid h-9 w-9 place-items-center rounded-xl ${TINT[k]}`}><Icon width={18} height={18} /></span>
          <p className="text-sm font-medium text-navy-700">{meta.label}</p>
        </div>
        {alert ? <LevelBadge level={alert.level} /> : isStale ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-900 ring-1 ring-amber-300">Stale</span> : null}
      </div>
      {trusted ? (
        <>
          <p className="mt-4 text-4xl font-semibold tabular-nums tracking-tight text-navy-900" data-testid={`value-${k}`}>
            {trusted.value.toFixed(meta.decimals)}<span className="ml-1.5 text-base font-medium text-navy-500">{meta.unit}</span>
          </p>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-navy-500" title={fmtDateTime(trusted.effective)}>Measured {fmtTime(trusted.effective)} · {ago(trusted.effective)}</p>
            <TrendChip trend={monitor ? trendOf(monitor, k) : null} />
          </div>
          {clinician && (
            <p className="mt-2 border-t border-slate-100 pt-2 text-xs text-navy-500">
              {b ? <>Personal baseline {b.median.toFixed(meta.decimals)} {meta.unit} ({trusted.value - b.median >= 0 ? "+" : ""}{(trusted.value - b.median).toFixed(meta.decimals)})</>
                : "Personal baseline: needs more readings"}
            </p>
          )}
        </>
      ) : (
        <div className="mt-4">
          <p className="text-2xl font-semibold text-slate-400">—</p>
          <p className="mt-1 text-xs text-navy-500">
            {waiting ? "Waiting for readings…" : monitor === null ? "Loading…" : monitor.vitals[k].latest ? "No trusted reading in this period" : "No reading available"}
          </p>
        </div>
      )}
    </div>
  );
}

type Range = "15" | "30" | "all";
const RANGES: { id: Range; label: string }[] = [{ id: "15", label: "15 min" }, { id: "30", label: "30 min" }, { id: "all", label: "All" }];

export function VitalCharts({ monitor, waiting = false, clinician = false }: { monitor: Monitor | null; waiting?: boolean; clinician?: boolean }) {
  const [range, setRange] = useState<Range>("all");
  const data = useMemo(() => {
    if (!monitor || waiting) return null;
    const all = Object.fromEntries(ORDER.map((k) => [k, trustedSeries(monitor, k)])) as Record<VitalKey, ReturnType<typeof trustedSeries>>;
    const latest = Math.max(0, ...ORDER.flatMap((k) => all[k].map((p) => p.ts)));
    const from = range === "all" ? 0 : latest - Number(range) * 60000;
    return Object.fromEntries(ORDER.map((k) => [k, all[k].filter((p) => p.ts >= from)])) as typeof all;
  }, [monitor, waiting, range]);
  const short = useMemo(() => {
    const ts = data ? ORDER.flatMap((k) => data[k].map((p) => p.ts)) : [];
    return ts.length > 1 && Math.max(...ts) - Math.min(...ts) < 10 * 60000;   // under 10 min: show seconds on the axis
  }, [monitor, waiting, range]);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="vital-charts">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-navy-900">Vital-sign trends</h2>
          <p className="text-xs text-navy-500">Readings stored in the FHIR server{monitor ? ` since ${fmtTime(monitor.windowStart)}` : ""}. Hover a line for exact values and times.{clinician ? " Likely sensor artifacts are excluded; the dashed line is the personal baseline." : ""}</p>
        </div>
        <div className="inline-flex rounded-lg bg-slate-100 p-1" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r.id} type="button" onClick={() => setRange(r.id)} aria-pressed={range === r.id}
              className={`rounded-md px-3 py-1 text-xs font-semibold ${range === r.id ? "bg-white text-navy-900 shadow-sm" : "text-navy-500 hover:text-navy-900"}`}>{r.label}</button>
          ))}
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {ORDER.map((k) => {
          const meta = VITAL_META[k];
          const pts = data?.[k] ?? [];
          const b = clinician && monitor && !waiting ? monitor.risk.news2.parameters[k]?.baseline : undefined;
          return (
            <div key={k} className="min-w-0 rounded-xl border border-slate-100 bg-slate-50/60 p-3" data-testid={`chart-${k}`}>
              <div className="mb-1 flex items-baseline justify-between">
                <p className="text-sm font-medium text-navy-900">{meta.short} <span className="text-xs font-normal text-navy-500">({meta.unit})</span></p>
                <p className="text-xs text-navy-500">{pts.length} reading{pts.length === 1 ? "" : "s"}</p>
              </div>
              <div className="h-44" aria-label={`${meta.label} chart`}>
                {pts.length > 1 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={pts} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="#e2e8f0" vertical={false} />
                      <XAxis dataKey="ts" type="number" domain={["dataMin", "dataMax"]} scale="time" tick={{ fontSize: 10, fill: "#47607c" }}
                        tickFormatter={(t) => new Date(t).toLocaleTimeString([], short ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : { hour: "2-digit", minute: "2-digit" })} minTickGap={36} />
                      <YAxis domain={DOMAIN[k]} tick={{ fontSize: 10, fill: "#47607c" }} width={34} tickCount={5} />
                      {b && <ReferenceLine y={b.median} stroke="#0d9488" strokeDasharray="4 3" />}
                      <Tooltip labelFormatter={(t) => fmtDateTime(new Date(Number(t)).toISOString())}
                        formatter={(v) => [`${Number(v).toFixed(meta.decimals)} ${meta.unit}`, meta.short]} />
                      <Line type="monotone" dataKey="value" stroke="#1d4063" strokeWidth={2.2} dot={pts.length < 30 ? { r: 2.5 } : false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="grid h-full place-items-center text-center text-xs text-navy-500">
                    {waiting ? "Waiting for readings…" : pts.length === 1 ? "One reading so far; a trend needs at least two" : "No readings in this time range"}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
