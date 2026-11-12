import { useEffect, useState } from "react";
import { SCENARIOS, resetSimulation, startSimulation, stopSimulation, type SimulatorState } from "../api";
import { Card, fmtTime } from "./ui";

type Status = "Idle" | "Running" | "Completed" | "Stopped" | "Error";

function statusOf(sim: SimulatorState | null | undefined, error: string | null, windowStart?: string): Status {
  if (error) return "Error";
  if (!sim || !sim.runId) return "Idle";
  if (!sim.running && windowStart && sim.startedAt && Date.parse(windowStart) > Date.parse(sim.startedAt) + 1000) return "Idle";   // reset after the run
  if (sim.running) return "Running";
  if (sim.stopped) return "Stopped";
  if (sim.rejected > 0 && sim.accepted === 0) return "Error";
  return "Completed";
}

/** Prefer the state returned by the last button press until the live feed has caught up with it. */
function pick(server: SimulatorState | null | undefined, local: SimulatorState | null): SimulatorState | null {
  if (!local) return server ?? null;
  if (!server || !server.runId) return local;
  if (server.runId !== local.runId) return (local.startedAt ?? "") >= (server.startedAt ?? "") ? local : server;
  if (!local.running && server.running) return local;   // Stop not yet reflected in the feed
  return server;
}

const TONE: Record<Status, string> = {
  Idle: "bg-slate-100 text-navy-700",
  Running: "bg-teal-100 text-teal-800",
  Completed: "bg-blue-100 text-blue-800",
  Stopped: "bg-amber-100 text-amber-800",
  Error: "bg-red-100 text-red-800",
};

/** Controls for the simulated monitoring source. All readings are labelled simulated and stored through the normal FHIR pipeline. */
export function SimulationPanel({ pid, sim, windowStart, onNewView, onChange }: {
  pid: string; sim: SimulatorState | null | undefined; windowStart?: string; onNewView: (windowStart: string) => void; onChange: () => void;
}) {
  const [scenario, setScenario] = useState<string>("deterioration");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [local, setLocal] = useState<SimulatorState | null>(null);
  useEffect(() => { setLocal(null); setError(null); }, [pid]);
  const mine = (s: SimulatorState | null | undefined) => (s && s.patientId === pid ? s : null);
  sim = pick(sim, local);
  const status = statusOf(sim, error, windowStart);
  const idleAfterReset = status === "Idle";
  const running = !!sim?.running;
  const pct = sim && sim.totalSteps && statusOf(sim, null, windowStart) !== "Idle" ? Math.round((100 * sim.step) / sim.totalSteps) : 0;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e: any) { setError(String(e?.message ?? e)); }
    finally { setBusy(false); onChange(); }
  };

  const btn = "rounded-lg px-4 py-2 text-sm font-semibold shadow-sm disabled:cursor-not-allowed disabled:opacity-40";
  return (
    <Card
      title="Live Simulation"
      right={<span data-testid="sim-status" className={`rounded-full px-3 py-1 text-xs font-semibold ${TONE[status]}`}>{status}</span>}
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm text-navy-700">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-navy-500">Scenario</span>
          <select
            data-testid="sim-scenario" value={scenario} disabled={running || busy}
            onChange={(e) => setScenario(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {SCENARIOS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </label>
        <button data-testid="sim-start" disabled={busy || running} onClick={() => act(async () => { const s = await startSimulation(pid, scenario); setLocal(mine(s)); if (s.startedAt) onNewView(new Date(Date.parse(s.startedAt)).toISOString().slice(0, 19) + "Z"); })}
          className={`${btn} bg-teal-700 text-white hover:bg-teal-800`}>▶ Start Simulation</button>
        <button data-testid="sim-stop" disabled={busy || !running} onClick={() => act(async () => setLocal(mine(await stopSimulation())))}
          className={`${btn} border border-slate-300 bg-white text-navy-900 hover:bg-slate-50`}>■ Stop Simulation</button>
        <button data-testid="sim-reset" disabled={busy} onClick={() => act(async () => { const r = await resetSimulation(pid); setLocal(mine(r.simulator)); onNewView(r.windowStart); })}
          className={`${btn} border border-slate-300 bg-white text-navy-900 hover:bg-slate-50`}>↺ Reset Simulation</button>
      </div>

      <div className="mt-4">
        <div className="flex justify-between text-xs text-navy-500">
          <span data-testid="sim-progress">
            {sim?.runId && !idleAfterReset ? `${sim.scenarioLabel ?? sim.scenario}: step ${sim.step} of ${sim.totalSteps}` : "No simulation run for this patient"}
          </span>
          {sim?.runId && !idleAfterReset && <span>{sim.accepted} readings stored in FHIR{sim.rejected ? ` · ${sim.rejected} rejected` : ""} · started {fmtTime(sim.startedAt)}</span>}
        </div>
        <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Simulation progress">
          <div className={`h-full rounded-full transition-all ${running ? "bg-teal-600" : "bg-slate-400"}`} style={{ width: `${pct}%` }} />
        </div>
      </div>
      {(error || sim?.lastError) && <p className="mt-2 text-xs text-red-700">{error ?? sim?.lastError}</p>}
      <p className="mt-3 text-xs text-navy-500">
        Readings are <strong>simulated</strong> (labelled as such in each FHIR Observation), sent one set every {sim?.intervalSeconds ?? 2} s through the normal
        ingestion pipeline and stored in HAPI FHIR. Start and Reset show only readings from the new run; earlier Observations stay stored in FHIR.
      </p>
    </Card>
  );
}
