import type { MonitoringSourceStatus, StatusResponse } from "../api";
import { BRAND } from "../brand";
import { ago, fmtTime } from "./ui";

function Pill({ ok, warn, label, value, testId }: { ok: boolean; warn?: boolean; label: string; value: string; testId: string }) {
  const dot = ok ? "bg-teal-300" : warn ? "bg-amber-300" : "bg-red-300";
  return (
    <div data-testid={testId} className="flex min-w-0 items-center gap-2 rounded-lg bg-white/10 px-3 py-1.5 text-xs">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden />
      <span className="text-teal-50/70">{label}</span>
      <span className="truncate font-semibold text-white">{value}</span>
    </div>
  );
}

export function Header({ status, source, lastUpdate }: {
  status: StatusResponse | "down" | null;
  source: MonitoringSourceStatus | null;
  lastUpdate: string | null;
}) {
  const api = status && status !== "down";
  const fhir = api ? status.services.fhir : null;
  const fhirOk = fhir?.status === "ok" && !!fhir.isR4;
  const simulated = (source?.latestSourceLabel ?? "").toLowerCase().includes("simulated") || (source?.simulatedSourcesRunning.length ?? 0) > 0;
  const srcValue = !source ? "—"
    : source.status === "receiving" ? `Receiving${simulated ? " · simulated source" : ""}`
    : source.status === "idle" ? `Idle · last data ${ago(source.lastIngestionAt)}`
    : "No source connected";
  return (
    <header className="bg-navy-900 text-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
        <a href="#/" className="flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="h-9 w-9" />
          <div>
            <h1 className="text-lg font-bold tracking-wide">AROGYA DRISHTI</h1>
            <p className="text-xs text-teal-50/80">Personalized Post-Discharge Patient Monitoring</p>
          </div>
        </a>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:flex lg:flex-wrap lg:justify-end" aria-live="polite">
          <Pill testId="status-api" ok={!!api} label="Backend" value={status === null ? "Checking…" : api ? "Connected" : "Unreachable"} />
          <Pill testId="status-fhir" ok={fhirOk} label="FHIR server" value={!api ? "Unknown" : fhirOk ? `Connected (R4 ${fhir?.fhirVersion})` : "Unavailable"} />
          <Pill testId="status-source" ok={source?.status === "receiving"} warn={source?.status !== "receiving"} label="Monitoring" value={srcValue} />
          <Pill testId="status-updated" ok={!!lastUpdate} warn={!lastUpdate} label="Last update" value={lastUpdate ? fmtTime(lastUpdate) : "—"} />
        </div>
      </div>
      <div className="bg-teal-800">
        <p role="note" className="mx-auto max-w-7xl px-4 py-1.5 text-xs text-white sm:px-6">
          {BRAND.disclaimer} Prototype: synthetic patients (Synthea) and simulated monitoring data; partial NEWS2-style scoring, not clinically validated.
        </p>
      </div>
    </header>
  );
}
