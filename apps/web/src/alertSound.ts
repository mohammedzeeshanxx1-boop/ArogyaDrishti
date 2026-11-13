/**
 * Audible alert tones for the Doctor Portal, generated with the Web Audio API (no audio files).
 *   WATCH  : one gentle beep
 *   REVIEW : two beeps
 *   URGENT : three faster beeps
 * Tones are scheduled on the AudioContext clock (not timers), so they also play in a background tab once audio
 * has been unlocked by a user interaction. Several alerts arriving together produce ONE pattern for the most
 * severe level, and a new pattern never overlaps one that is still playing. If audio is unavailable or blocked,
 * nothing throws: visual pop-ups and the bell are unaffected.
 */
import type { RiskLevel } from "./api";

type Level = Exclude<RiskLevel, "NORMAL">;
interface Tone { freq: number; count: number; beepMs: number; gapMs: number }

export const PATTERNS: Record<Level, Tone> = {
  WATCH: { freq: 660, count: 1, beepMs: 180, gapMs: 0 },
  REVIEW: { freq: 880, count: 2, beepMs: 160, gapMs: 170 },
  URGENT: { freq: 1046, count: 3, beepMs: 110, gapMs: 90 },
};
const RANK: Record<Level, number> = { WATCH: 1, REVIEW: 2, URGENT: 3 };
const VOLUME = 0.12;          // moderate peak gain
const STORAGE_KEY = "arogya.alertSound";

type Listener = (s: SoundState) => void;
export interface SoundState { enabled: boolean; unlocked: boolean; supported: boolean }

let ctx: AudioContext | null = null;
let busyUntil = 0;            // AudioContext time when the current pattern ends
const listeners = new Set<Listener>();

function readPref(): boolean {
  try { return window.localStorage.getItem(STORAGE_KEY) !== "off"; } catch { return true; }
}
let enabled = typeof window !== "undefined" ? readPref() : true;

function Ctor(): typeof AudioContext | null {
  if (typeof window === "undefined") return null;
  return (window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext) ?? null;
}

export function soundState(): SoundState {
  return { enabled, unlocked: !!ctx && ctx.state === "running", supported: !!Ctor() };
}
const emit = () => { const s = soundState(); listeners.forEach((l) => l(s)); };
export function subscribe(l: Listener): () => void { listeners.add(l); return () => { listeners.delete(l); }; }

/** Create/resume the AudioContext. Must be called from a user gesture (click, key press) to satisfy autoplay rules. */
export async function unlock(): Promise<boolean> {
  const C = Ctor();
  if (!C) return false;
  try {
    if (!ctx) ctx = new C();
    if (ctx.state === "suspended") await ctx.resume();
  } catch { /* blocked: visual alerts continue */ }
  emit();
  return !!ctx && ctx.state === "running";
}

/** Unlock audio on the first user interaction anywhere on the page. */
export function unlockOnFirstInteraction(): () => void {
  const handler = () => { void unlock(); remove(); };
  const remove = () => { window.removeEventListener("pointerdown", handler); window.removeEventListener("keydown", handler); };
  window.addEventListener("pointerdown", handler, { once: true });
  window.addEventListener("keydown", handler, { once: true });
  return remove;
}

export function setEnabled(on: boolean): void {
  enabled = on;
  try { window.localStorage.setItem(STORAGE_KEY, on ? "on" : "off"); } catch { /* preference not persisted */ }
  emit();
}

function schedule(level: Level): boolean {
  if (!ctx || ctx.state !== "running") return false;
  const p = PATTERNS[level];
  const start = Math.max(ctx.currentTime + 0.02, busyUntil);   // never overlap a pattern that is still playing
  let t = start;
  for (let i = 0; i < p.count; i++) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = p.freq;
    const dur = p.beepMs / 1000;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(VOLUME, t + 0.012);       // short attack, no click
    gain.gain.setValueAtTime(VOLUME, t + dur - 0.03);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);         // short release
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + dur + 0.02);
    t += dur + p.gapMs / 1000;
  }
  busyUntil = t + 0.25;
  return true;
}

/**
 * Called with the alert events that just produced pop-ups (already de-duplicated by event id).
 * Plays one pattern for the most severe non-NORMAL level. Returns the level played, or null.
 */
export function playForEvents(levels: RiskLevel[]): Level | null {
  if (!enabled) return null;
  const top = levels.filter((l): l is Level => l !== "NORMAL").sort((a, b) => RANK[b] - RANK[a])[0];
  if (!top) return null;
  try { return schedule(top) ? top : null; } catch { return null; }
}

/** "Test sound": unlocks audio (user gesture) and plays the pattern even if alerts are muted. */
export async function testSound(level: Level = "REVIEW"): Promise<boolean> {
  if (!(await unlock())) return false;
  try { return schedule(level); } catch { return false; }
}

/** For tests only. */
export function _resetForTests(): void { ctx = null; busyUntil = 0; enabled = readPref(); listeners.clear(); }
