import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import {
  acknowledgeAlert, fetchNotifications, markAllNotificationsRead, markNotificationsRead, notificationsSocketUrl,
  type AlertEvent, type RiskLevel,
} from "./api";
import { IconAlert, IconBell, IconCheck, IconX } from "./components/icons";
import { LevelBadge, ago, fmtDateTime, fmtTime } from "./components/ui";
import { LEVEL_MESSAGE } from "./components/risk";

/**
 * Doctor notifications. The server's recorded risk events are the only source: nothing is assessed here.
 * - On connect the server sends a cursor (latest event id); only events after it can pop up, so old history
 *   is never replayed as new on sign-in or refresh. Each event id pops up at most once.
 * - WebSocket push with reconnection (backoff); while it is down, cursor-based polling of GET /api/notifications.
 * - Read state and acknowledgements are stored on the server per doctor account.
 */
interface Ctx {
  items: AlertEvent[];
  unread: number;
  connection: "live" | "polling" | "connecting";
  markRead: (ids: number[]) => Promise<void>;
  markAllRead: () => Promise<void>;
  acknowledge: (id: number) => Promise<void>;
  setPanelOpen: (open: boolean) => void;
}
const NotificationContext = createContext<Ctx | null>(null);
export const useNotifications = () => useContext(NotificationContext);

const AUTO_DISMISS: Record<RiskLevel, number | null> = { NORMAL: 8000, WATCH: 10000, REVIEW: 20000, URGENT: null };
const POLL_MS = 4000;

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<AlertEvent[]>([]);
  const [unread, setUnread] = useState(0);
  const [toasts, setToasts] = useState<AlertEvent[]>([]);
  const [connection, setConnection] = useState<Ctx["connection"]>("connecting");
  const [panelOpen, setPanelOpen] = useState(false);   // the bell panel lists the same events; toasts step aside while it is open
  const cursor = useRef<number | null>(null);
  const seen = useRef<Set<number>>(new Set());

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const deliver = useCallback((events: AlertEvent[], unreadCount: number) => {
    const fresh = events.filter((e) => !seen.current.has(e.id));
    fresh.forEach((e) => seen.current.add(e.id));
    if (fresh.length) {
      setItems((cur) => [...[...fresh].reverse(), ...cur.filter((c) => !fresh.some((f) => f.id === c.id))].slice(0, 50));
      setToasts((cur) => [...[...fresh].reverse().filter((e) => !e.read), ...cur].slice(0, 5));
      fresh.forEach((e) => {
        const ms = AUTO_DISMISS[e.level];
        if (ms) window.setTimeout(() => dismiss(e.id), ms);
      });
    }
    setUnread(unreadCount);
  }, [dismiss]);

  useEffect(() => {
    let alive = true;
    let ws: WebSocket | null = null;
    let poll: number | undefined;
    let retry: number | undefined;
    let backoff = 2000;

    const startPolling = () => {
      if (!alive || poll) return;
      setConnection("polling");
      poll = window.setInterval(async () => {
        try {
          if (cursor.current === null) {           // never connected: establish the cursor without replaying history
            const f = await fetchNotifications();
            // Only establishes the polling cursor. Items are not marked as seen here: if the WebSocket's first
            // message is slow (e.g. right after an API restart), it still delivers events newer than its own
            // connection cursor, and those must still pop up. Older history is never sent as new events.
            cursor.current = f.latestId; setItems(f.items); setUnread(f.unread);
            return;
          }
          const f = await fetchNotifications(cursor.current, 50);
          if (f.items.length) cursor.current = f.items[f.items.length - 1].id;
          deliver(f.items, f.unread);
        } catch { /* keep polling; the shell shows backend status */ }
      }, POLL_MS);
    };
    const stopPolling = () => { if (poll) { window.clearInterval(poll); poll = undefined; } };

    const connect = () => {
      if (!alive) return;
      try { ws = new WebSocket(notificationsSocketUrl(cursor.current ?? undefined)); } catch { startPolling(); return; }
      ws.onmessage = (e) => {
        let m: any;
        try { m = JSON.parse(String(e.data)); } catch { return; }
        if (m.type === "hello") {
          const first = cursor.current === null;
          if (first) {
            (m.items as AlertEvent[]).forEach((i) => seen.current.add(i.id));
            cursor.current = m.cursor;
          }
          setItems((cur) => {
            const merged = [...(m.items as AlertEvent[])];
            cur.forEach((c) => { if (!merged.some((x) => x.id === c.id)) merged.push(c); });
            return merged.sort((a, b) => b.id - a.id).slice(0, 50);
          });
          setUnread(m.unread);
          setConnection("live"); stopPolling(); backoff = 2000;
        } else if (m.type === "events") {
          cursor.current = Math.max(cursor.current ?? 0, m.cursor);
          deliver(m.items as AlertEvent[], m.unread);
        } else if (m.type === "ping") {
          setUnread(m.unread);
        }
      };
      ws.onclose = (e) => {
        if (!alive) return;
        startPolling();
        if (e.code === 4401 || e.code === 4403) return;
        retry = window.setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 30000);
      };
    };
    connect();
    const watchdog = window.setTimeout(() => { if (alive && cursor.current === null) startPolling(); }, 8000);
    return () => {
      alive = false; window.clearTimeout(watchdog); window.clearTimeout(retry); stopPolling();
      if (ws) { ws.onclose = null; ws.close(); }
    };
  }, [deliver]);

  const markRead = useCallback(async (ids: number[]) => {
    if (!ids.length) return;
    const r = await markNotificationsRead(ids);
    setItems((cur) => cur.map((i) => (ids.includes(i.id) ? { ...i, read: true } : i)));
    setUnread(r.unread);
  }, []);
  const markAllRead = useCallback(async () => {
    await markAllNotificationsRead();
    setItems((cur) => cur.map((i) => ({ ...i, read: true })));
    setUnread(0);
  }, []);
  const acknowledge = useCallback(async (id: number) => {
    const a = await acknowledgeAlert(id);
    setItems((cur) => cur.map((i) => (i.id === id ? { ...i, read: true, acknowledgedByMe: true,
      acknowledgements: [...(i.acknowledgements ?? []), { username: a.username, acknowledgedAt: a.acknowledgedAt }] } : i)));
    const f = await fetchNotifications(undefined, 1).catch(() => null);
    if (f) setUnread(f.unread);
  }, []);

  return (
    <NotificationContext.Provider value={{ items, unread, connection, markRead, markAllRead, acknowledge, setPanelOpen }}>
      {children}
      <ToastStack toasts={panelOpen ? [] : toasts} onDismiss={dismiss} onView={(t) => { dismiss(t.id); void markRead([t.id]).catch(() => {}); window.location.hash = `#/doctor/patients/${encodeURIComponent(t.patient_id)}`; }} />
    </NotificationContext.Provider>
  );
}

const ACCENT: Record<RiskLevel, string> = {
  URGENT: "border-red-600 bg-red-50", REVIEW: "border-orange-500 bg-orange-50", WATCH: "border-amber-400 bg-white", NORMAL: "border-teal-500 bg-white",
};
const ICON_TONE: Record<RiskLevel, string> = { URGENT: "bg-red-600 text-white", REVIEW: "bg-orange-500 text-white", WATCH: "bg-amber-100 text-amber-800", NORMAL: "bg-teal-50 text-teal-700" };

function ToastStack({ toasts, onDismiss, onView }: { toasts: AlertEvent[]; onDismiss: (id: number) => void; onView: (t: AlertEvent) => void }) {
  return (
    <div className="pointer-events-none fixed right-4 top-20 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-3" aria-live="polite" data-testid="toast-stack">
      {toasts.map((t) => {
        const Icon = t.level === "URGENT" || t.level === "REVIEW" ? IconAlert : t.level === "NORMAL" ? IconCheck : IconBell;
        return (
          <div key={t.id} role={t.level === "URGENT" ? "alert" : "status"} data-testid="toast" data-level={t.level} data-event={t.id}
            className={`pointer-events-auto overflow-hidden rounded-xl border-l-4 shadow-lg ring-1 ring-slate-200 ${ACCENT[t.level]} ${t.level === "URGENT" ? "animate-[pulse_1.2s_ease-in-out_2]" : ""}`}>
            <div className="flex gap-3 p-4">
              <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${ICON_TONE[t.level]}`}><Icon width={18} height={18} /></span>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <p className="truncate font-semibold text-navy-900" data-testid="toast-patient">{t.patientName ?? "Patient"}</p>
                  <button type="button" onClick={() => onDismiss(t.id)} aria-label="Dismiss notification" className="-mr-1 -mt-1 rounded p-1 text-navy-500 hover:bg-black/5"><IconX width={16} height={16} /></button>
                </div>
                <div className="mt-0.5 flex items-center gap-2"><LevelBadge level={t.level} /><span className="text-xs text-navy-500">{fmtTime(t.measured_at ?? t.created_at)}</span></div>
                {t.level !== "NORMAL" && <p className="mt-1.5 text-sm font-semibold text-navy-900">{LEVEL_MESSAGE[t.level]}</p>}
                <p className="mt-1 text-sm text-navy-700">{t.summary}</p>
                <button type="button" onClick={() => onView(t)} data-testid="toast-view"
                  className="mt-3 rounded-lg bg-navy-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-navy-700">View patient</button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function NotificationBell() {
  const ctx = useNotifications();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState<number | "all" | null>(null);
  useEffect(() => { ctx?.setPanelOpen(open); }, [open, ctx]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc); document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);
  if (!ctx) return null;
  const run = async (key: number | "all", fn: () => Promise<void>) => { setBusy(key); try { await fn(); } catch { /* shown via list state */ } finally { setBusy(null); } };
  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="dialog" data-testid="bell"
        aria-label={`Notifications, ${ctx.unread} unread`} className="relative rounded-full p-2 text-navy-700 hover:bg-slate-100">
        <IconBell width={22} height={22} />
        {ctx.unread > 0 && <span data-testid="bell-count" className="absolute -right-0.5 -top-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-red-600 px-1 text-[11px] font-bold text-white">{ctx.unread > 99 ? "99+" : ctx.unread}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" data-testid="bell-panel"
          className="absolute right-0 top-12 z-50 w-[min(420px,calc(100vw-2rem))] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <div><p className="font-semibold text-navy-900">Notifications</p>
              <p className="text-xs text-navy-500">{ctx.unread} unread · {ctx.connection === "live" ? "live" : ctx.connection === "polling" ? "checking every few seconds" : "connecting…"}</p></div>
            <button type="button" disabled={ctx.unread === 0 || busy !== null} onClick={() => run("all", ctx.markAllRead)} data-testid="mark-all-read"
              className="text-xs font-semibold text-teal-700 hover:underline disabled:text-slate-400 disabled:no-underline">Mark all as read</button>
          </div>
          <ul className="max-h-[60vh] divide-y divide-slate-100 overflow-y-auto" data-testid="bell-list">
            {ctx.items.length === 0 && <li className="px-4 py-6 text-center text-sm text-navy-500">No risk events yet. New events appear here as they are recorded.</li>}
            {ctx.items.slice(0, 20).map((i) => (
              <li key={i.id} className={`px-4 py-3 ${i.read ? "" : "bg-teal-50/50"}`} data-testid="bell-item" data-read={i.read ? "true" : "false"}>
                <a href={`#/doctor/patients/${encodeURIComponent(i.patient_id)}`} onClick={() => { setOpen(false); if (!i.read) void ctx.markRead([i.id]).catch(() => {}); }} className="block">
                  <div className="flex items-center gap-2">
                    {!i.read && <span className="h-2 w-2 rounded-full bg-teal-600" aria-label="Unread" />}
                    <span className="truncate text-sm font-semibold text-navy-900">{i.patientName ?? "Patient"}</span>
                    <LevelBadge level={i.level} />
                    <span className="ml-auto shrink-0 text-xs text-navy-500" title={fmtDateTime(i.created_at)}>{ago(i.created_at)}</span>
                  </div>
                  <p className="mt-1 text-xs text-navy-700">{i.summary}</p>
                </a>
                <div className="mt-2 flex gap-3 text-xs">
                  {!i.read && <button type="button" disabled={busy !== null} onClick={() => run(i.id, () => ctx.markRead([i.id]))} className="font-semibold text-navy-700 hover:underline">Mark as read</button>}
                  {i.acknowledgedByMe
                    ? <span className="inline-flex items-center gap-1 font-medium text-teal-700"><IconCheck width={14} height={14} />Acknowledged</span>
                    : <button type="button" disabled={busy !== null} onClick={() => run(i.id, () => ctx.acknowledge(i.id))} data-testid="bell-ack" className="font-semibold text-teal-700 hover:underline">Acknowledge</button>}
                </div>
              </li>
            ))}
          </ul>
          <a href="#/doctor/alerts" onClick={() => setOpen(false)} className="block border-t border-slate-100 px-4 py-2.5 text-center text-sm font-semibold text-teal-700 hover:bg-slate-50">Open alert history</a>
        </div>
      )}
    </div>
  );
}
