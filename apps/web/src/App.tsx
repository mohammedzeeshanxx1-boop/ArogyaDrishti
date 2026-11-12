import { useCallback, useEffect, useState } from "react";
import { fetchMonitoringStatus, fetchStatus, type MonitoringSourceStatus, type StatusResponse } from "./api";
import { BRAND } from "./brand";
import { Header } from "./components/Header";
import { Overview } from "./components/Overview";
import { PatientDetail } from "./components/PatientDetail";

type Route = { page: "overview" } | { page: "patient"; id: string };

function parseRoute(hash: string): Route {
  const m = hash.match(/^#\/patient\/([^/?#]+)/);
  return m ? { page: "patient", id: decodeURIComponent(m[1]) } : { page: "overview" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  const [status, setStatus] = useState<StatusResponse | "down" | null>(null);
  const [source, setSource] = useState<MonitoringSourceStatus | null>(null);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);
  const touch = useCallback(() => setLastUpdate(new Date().toISOString()), []);

  useEffect(() => {
    const onHash = () => { setRoute(parseRoute(window.location.hash)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const load = () => {
      fetchStatus().then(setStatus).catch(() => setStatus("down"));
      fetchMonitoringStatus().then(setSource).catch(() => setSource(null));
    };
    load();
    const t = window.setInterval(load, 10000);
    return () => window.clearInterval(t);
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-surface font-sans text-navy-900">
      <Header status={status} source={source} lastUpdate={lastUpdate} />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        {route.page === "overview" ? <Overview onUpdate={touch} /> : <PatientDetail key={route.id} pid={route.id} onUpdate={touch} />}
      </main>
      <footer className="border-t border-slate-200 bg-white">
        <p className="mx-auto max-w-7xl px-4 py-3 text-xs text-navy-700 sm:px-6">
          {BRAND.name} prototype · {BRAND.disclaimer} Not a medical device; not clinically validated. Patient records are synthetic; monitoring data is simulated unless a source states otherwise.
        </p>
      </footer>
    </div>
  );
}
