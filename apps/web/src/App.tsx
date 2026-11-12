import { useCallback, useEffect, useState } from "react";
import { fetchStatus, probeWebSocket, type ServiceState, type StatusResponse } from "./api";
import { BRAND } from "./brand";

const STATE_LABEL: Record<ServiceState, string> = {
  ok: "Connected",
  unreachable: "Unreachable",
  error: "Error",
  checking: "Checking…",
};

const STATE_STYLE: Record<ServiceState, string> = {
  ok: "bg-teal-50 text-teal-700 ring-teal-600/30",
  unreachable: "bg-amber-50 text-amber-800 ring-amber-600/30",
  error: "bg-red-50 text-red-800 ring-red-600/30",
  checking: "bg-slate-100 text-navy-500 ring-slate-400/30",
};

function ServiceCard({ name, role, state, detail }: { name: string; role: string; state: ServiceState; detail: string }) {
  return (
    <li className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-navy-900">{name}</h3>
          <p className="mt-0.5 text-sm text-navy-500">{role}</p>
        </div>
        <span
          data-testid={`state-${name}`}
          className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${STATE_STYLE[state]}`}
        >
          {STATE_LABEL[state]}
        </span>
      </div>
      <p className="mt-4 text-sm text-navy-700">{detail}</p>
    </li>
  );
}

export default function App() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [apiState, setApiState] = useState<ServiceState>("checking");
  const [wsState, setWsState] = useState<ServiceState>("checking");

  const refresh = useCallback(async () => {
    setApiState("checking");
    setWsState("checking");
    try {
      setStatus(await fetchStatus());
      setApiState("ok");
    } catch {
      setStatus(null);
      setApiState("unreachable");
    }
    setWsState((await probeWebSocket()) ? "ok" : "unreachable");
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const fhir = status?.services.fhir;
  const store = status?.services.eventStore;
  const dependentState = (s?: ServiceState): ServiceState => (apiState === "ok" ? (s ?? "error") : apiState);

  return (
    <div className="flex min-h-screen flex-col font-sans">
      <header className="bg-navy-900 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-5">
          <div className="flex items-center gap-3">
            <img src="/favicon.svg" alt="" className="h-10 w-10" />
            <div>
              <h1 className="text-xl font-semibold tracking-tight">{BRAND.name}</h1>
              <p className="text-sm text-teal-50/80">{BRAND.tagline}</p>
            </div>
          </div>
          <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium">
            Build checkpoint {status?.checkpoint ?? "C0"} · scaffold
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        <section aria-labelledby="services-heading">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="services-heading" className="text-lg font-semibold">
                Service status
              </h2>
              <p className="mt-1 text-sm text-navy-500" aria-live="polite">
                {status ? `Last checked ${new Date(status.checkedAt).toLocaleTimeString()}` : "Live checks against the running stack."}
              </p>
            </div>
            <button
              type="button"
              onClick={() => void refresh()}
              className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-600"
            >
              Re-check
            </button>
          </div>

          <ul className="mt-5 grid gap-4 sm:grid-cols-2">
            <ServiceCard
              name="API"
              role="FastAPI monitoring service"
              state={apiState}
              detail={apiState === "ok" ? `Version ${status?.services.api.version ?? "unknown"}` : "No response from /api/v1/status."}
            />
            <ServiceCard
              name="HAPI FHIR"
              role="FHIR R4 clinical data store"
              state={dependentState(fhir?.status)}
              detail={
                fhir?.status === "ok"
                  ? `FHIR ${fhir.fhirVersion ?? "version not declared"}${fhir.isR4 ? " (R4)" : " — not R4"}`
                  : (fhir?.detail ?? "Status is reported by the API.")
              }
            />
            <ServiceCard
              name="Event store"
              role="SQLite, app-only event metadata"
              state={dependentState(store?.status)}
              detail={store?.status === "ok" ? `Schema version ${store.schemaVersion}` : (store?.detail ?? "Status is reported by the API.")}
            />
            <ServiceCard
              name="Live channel"
              role="WebSocket transport"
              state={wsState}
              detail={wsState === "ok" ? "Heartbeat handshake succeeded." : "No heartbeat from /ws/heartbeat."}
            />
          </ul>
        </section>

        <section aria-labelledby="scope-heading" className="mt-8 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 id="scope-heading" className="text-lg font-semibold">
            What this build contains
          </h2>
          <p className="mt-2 max-w-3xl text-sm text-navy-700">
            This is the project scaffold. It starts the services and verifies that they can reach each other. Patient
            monitoring, alerting and replay are not implemented yet, so no patient data or clinical output is shown.
          </p>
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <p role="note" className="mx-auto max-w-6xl px-6 py-4 text-sm font-medium text-navy-700">
          {BRAND.disclaimer}
        </p>
      </footer>
    </div>
  );
}
