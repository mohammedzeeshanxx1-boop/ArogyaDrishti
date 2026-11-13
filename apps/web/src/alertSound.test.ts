import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PATTERNS, _resetForTests, playForEvents, setEnabled, testSound, unlock } from "./alertSound";
import { FakeAudioContext } from "./testAudio";

describe("alert sounds", () => {
  beforeEach(() => { localStorage.clear(); FakeAudioContext.instances = []; vi.stubGlobal("AudioContext", FakeAudioContext); _resetForTests(); });
  afterEach(() => vi.unstubAllGlobals());

  it("plays one, two and three beeps for WATCH, REVIEW and URGENT, without overlap", async () => {
    await unlock();
    const ctx = FakeAudioContext.instances[0];
    expect(playForEvents(["WATCH"])).toBe("WATCH");
    expect(ctx.starts.length).toBe(1);
    expect(playForEvents(["REVIEW"])).toBe("REVIEW");
    expect(ctx.starts.length).toBe(3);
    expect(playForEvents(["URGENT"])).toBe("URGENT");
    expect(ctx.starts.length).toBe(6);
    expect(ctx.starts.map((s) => s.freq)).toEqual([660, 880, 880, 1046, 1046, 1046]);
    const t = ctx.starts.map((s) => s.t);
    expect(t.every((x, i) => i === 0 || x > t[i - 1])).toBe(true);           // strictly sequential: patterns never overlap
    expect(t[4] - t[3]).toBeLessThan(t[2] - t[1]);                            // URGENT beeps are faster than REVIEW
    expect(PATTERNS.URGENT.beepMs).toBeLessThan(PATTERNS.REVIEW.beepMs);
  });

  it("plays a single pattern for the most severe level when several alerts arrive together; nothing for NORMAL", async () => {
    await unlock();
    const ctx = FakeAudioContext.instances[0];
    expect(playForEvents(["WATCH", "URGENT", "REVIEW"])).toBe("URGENT");
    expect(ctx.starts.length).toBe(3);
    expect(playForEvents(["NORMAL"])).toBeNull();
    expect(playForEvents([])).toBeNull();
    expect(ctx.starts.length).toBe(3);
  });

  it("respects the saved mute preference; test sound still works", async () => {
    await unlock();
    setEnabled(false);
    expect(localStorage.getItem("arogya.alertSound")).toBe("off");
    _resetForTests();                                                          // preference survives a reload
    await unlock();
    expect(playForEvents(["URGENT"])).toBeNull();
    expect(await testSound("REVIEW")).toBe(true);
    setEnabled(true);
    expect(playForEvents(["WATCH"])).toBe("WATCH");
  });

  it("does nothing (and never throws) before audio is unlocked or when unsupported", () => {
    expect(playForEvents(["URGENT"])).toBeNull();
    vi.stubGlobal("AudioContext", undefined);
    _resetForTests();
    expect(playForEvents(["URGENT"])).toBeNull();
  });
});
