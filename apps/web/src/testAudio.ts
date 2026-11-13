// Test helper: a minimal AudioContext that records scheduled beeps.
export class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  state: "running" | "suspended" = "suspended";
  currentTime = 0;
  destination = {};
  starts: { t: number; freq: number }[] = [];
  constructor() { FakeAudioContext.instances.push(this); }
  async resume() { this.state = "running"; }
  createGain() { return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (d: unknown) => d }; }
  createOscillator() {
    const self = this;
    const o = { type: "", frequency: { value: 0 }, connect: (g: { connect: (d: unknown) => unknown }) => g, start(t: number) { self.starts.push({ t, freq: o.frequency.value }); }, stop() {} };
    return o;
  }
}

