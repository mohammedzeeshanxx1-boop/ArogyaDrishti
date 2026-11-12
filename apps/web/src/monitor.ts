import { useCallback, useEffect, useRef, useState } from "react";
import { fetchMonitor, fetchProfile, monitorSocketUrl, type Monitor, type PatientProfile } from "./api";

const POLL_MS = 3000;
const WATCHDOG_MS = 10000;

export type LiveMode = "connecting" | "websocket" | "polling";

/**
 * Live monitor data for one patient from the backend (never generated here).
 * WebSocket push first; while the socket is down the hook polls every 3 s and retries the socket with backoff.
 * After Start/Reset (markView), frames built for the previous view are dropped for up to 8 s.
 */
export function useMonitor(pid: string | null, onUpdate?: () => void) {
  const [monitor, setMonitor] = useState<Monitor | null>(null);
  const [live, setLive] = useState<LiveMode>("connecting");
  const [error, setError] = useState<string | null>(null);
  const updateRef = useRef(onUpdate);
  updateRef.current = onUpdate;
  const guard = useRef<{ view: string; until: number }>({ view: "", until: 0 });
  const [pending, setPending] = useState<string | null>(null);

  const accept = useCallback((m: Monitor) => {
    const g = guard.current;
    if (Date.now() < g.until) {
      if (m.windowStart < g.view) return;
      guard.current = { view: "", until: 0 }; setPending(null);
    }
    setMonitor(m); setError(null); updateRef.current?.();
  }, []);

  const markView = useCallback((windowStart: string) => {
    guard.current = { view: windowStart, until: Date.now() + 8000 }; setPending(windowStart);
    window.setTimeout(() => { if (guard.current.view === windowStart) { guard.current = { view: "", until: 0 }; setPending(null); } }, 8000);
  }, []);

  const poll = useCallback(async () => {
    if (!pid) return;
    try { accept(await fetchMonitor(pid)); }
    catch (e: any) { setError(String(e?.message ?? e)); }
  }, [pid, accept]);

  useEffect(() => {
    if (!pid) return;
    let alive = true;
    let timer: number | undefined;
    let retry: number | undefined;
    let ws: WebSocket | null = null;
    let backoff = 2000;
    guard.current = { view: "", until: 0 }; setPending(null); setMonitor(null);
    setLive("connecting");

    const startPolling = () => {
      if (!alive || timer) return;
      setLive("polling");
      timer = window.setInterval(() => void poll(), POLL_MS);
    };
    const stopPolling = () => { if (timer) { window.clearInterval(timer); timer = undefined; } };
    const connect = () => {
      if (!alive) return;
      try { ws = new WebSocket(monitorSocketUrl(pid)); } catch { startPolling(); return; }
      ws.onmessage = (e) => {
        try {
          const m = JSON.parse(String(e.data));
          if (m.type === "monitor" && alive) { accept(m.data); setLive("websocket"); stopPolling(); backoff = 2000; }
        } catch { /* ignore malformed frames */ }
      };
      ws.onclose = (e) => {
        if (!alive) return;
        startPolling();
        if (e.code === 4401 || e.code === 4403) return;   // not signed in / not allowed: polling reports the error
        retry = window.setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 30000);
      };
      ws.onerror = () => { /* onclose follows */ };
    };
    connect();
    const watchdog = window.setTimeout(() => { if (alive && !ws?.readyState) startPolling(); }, WATCHDOG_MS);
    void poll();
    return () => {
      alive = false; window.clearTimeout(watchdog); window.clearTimeout(retry); stopPolling();
      if (ws) { ws.onclose = null; ws.close(); }
    };
  }, [pid, poll, accept]);

  return { monitor, live, error, refresh: poll, markView, pending: pending !== null, viewStart: pending ?? monitor?.windowStart };
}

export function useProfile(pid: string | null) {
  const [profile, setProfile] = useState<PatientProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!pid) return;
    let alive = true;
    setProfile(null); setError(null);
    fetchProfile(pid).then((p) => alive && setProfile(p)).catch((e) => alive && setError(String(e?.message ?? e)));
    return () => { alive = false; };
  }, [pid]);
  return { profile, error };
}
