import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const now = new Date().toISOString();
const status = { checkedAt: now, services: { api: { status: "ok" }, fhir: { status: "ok", isR4: true, fhirVersion: "4.0.1" }, eventStore: { status: "ok" } } };
const source = { status: "receiving", lastIngestionAt: now, secondsSinceLastIngestion: 3, latestSourceLabel: "Arogya Drishti virtual wearable (simulated)", simulatedSourcesRunning: [], physicalDevicesConnected: 0 };
const baseMon = { recentWindowMinutes: 60, staleAfterMinutes: 15, requiredTrustedVitals: 3 };
const overview = {
  generatedAt: now, recentWindowMinutes: 60, staleAfterMinutes: 15,
  patients: [
    { id: "p1", name: "Ariane992 Kirlin939", gender: "female", age: 57, lastDischarge: "2026-08-19T00:00:00Z", activeConditions: 11, activeMedications: 4,
      monitoring: { ...baseMon, assessable: true, level: "URGENT", monitoringStatus: "active", lastObservationAt: now, trustedVitals: 4, topReason: "SpO2 88 % scores 3.",
        latest: { heart_rate: { value: 134, effective: now, observation: "Observation/1", score: 3, baseline: null }, spo2: { value: 88, effective: now, observation: "Observation/2", score: 3, baseline: null } } } },
    { id: "p2", name: "Victor265 Ernser583", gender: "male", age: 82, lastDischarge: "2026-06-04T00:00:00Z", activeConditions: 22, activeMedications: 12,
      monitoring: { ...baseMon, assessable: false, level: null, monitoringStatus: "no_recent_data", lastObservationAt: null, trustedVitals: 0, latest: {} } },
  ],
};
const profile = {
  patient: { id: "p1", name: "Ariane992 Kirlin939", gender: "female", age: 57, birthDate: "1969-08-12" },
  discharge: { encounter: "Encounter/e1", discharged: "2026-08-19T00:00:00Z", facility: "Test Hospital", inpatientStays: 1 },
  activeConditions: [{ id: "c1", condition: "Ischemic heart disease (disorder)" }],
  activeMedications: [{ id: "m1", medication: "clopidogrel 75 MG Oral Tablet" }],
  allergies: [],
};
const series = (v: number) => [{ effective: now, value: v - 1, observation: "Observation/9" }, { effective: now, value: v, observation: "Observation/10" }];
const vit = (label: string, unit: string, v: number) => ({ label, unit, series: series(v), latest: series(v)[1] });
const monitor = {
  patientId: "p1", windowStart: now, evaluatedAt: now, observationCount: 8,
  vitals: { heart_rate: vit("Heart rate", "/min", 134), spo2: vit("SpO2", "%", 88), respiratory_rate: vit("Respiratory rate", "/min", 31), body_temperature: vit("Temperature", "°C", 39.3) },
  risk: {
    level: "URGENT", readingsConsidered: 8, label: "NEWS2-style score (partial: 4 of 7 parameters) ... not clinically validated.",
    summary: "x", suppressed: [], suppressedCount: 0,
    alerts: [{ level: "URGENT", ruleType: "news2-aggregate", vital: null, vitalLabel: "NEWS2-style aggregate", value: 11, unit: "points", rule: "≥7 URGENT", observation: "Observation/10", effective: now, reason: "NEWS2-style partial aggregate 11." }],
    news2: { total: 11, level: "URGENT", measuredParameters: 4, of: 7, partial: true, spo2Scale: 1, notAvailable: ["systolic blood pressure", "air or oxygen", "consciousness (ACVPU)"],
      parameters: { heart_rate: { score: 3, value: 134, observation: "Observation/10", effective: now, bands: "Pulse", baseline: { median: 76, mad: 2, n: 40, from: now, to: now } } } },
  },
  assessment: { ...baseMon, assessable: true, level: "URGENT", monitoringStatus: "active", lastObservationAt: now, trustedVitals: 4, latest: {}, sources: ["Arogya Drishti virtual wearable (simulated)"] },
  scale2: { patientId: "p1", scale: 1, eligible: false, rule: "", flag: null, supportingConditions: [] },
};

const doctor = { username: "doctor", role: "doctor", patientId: null, displayName: "Demo clinician" };
const patientUser = { username: "ariane.kirlin", role: "patient", patientId: "p1", displayName: "Ariane Kirlin" };

/** Routes by URL prefix; a value of {__status, body} answers with that HTTP status. */
function routeFetch(map: Record<string, unknown>) {
  return vi.fn(async (url: string) => {
    const key = Object.keys(map).filter((k) => url.startsWith(k)).sort((a, b) => b.length - a.length)[0];
    if (!key) return { ok: false, status: 404, json: async () => ({}) };
    const v: any = map[key];
    if (v && typeof v === "object" && "__status" in v) return { ok: v.__status < 400, status: v.__status, json: async () => v.body };
    return { ok: true, status: 200, json: async () => v };
  });
}

class FailingSocket {
  onmessage: unknown = null; onerror: (() => void) | null = null; onclose: ((e: { code: number }) => void) | null = null;
  readyState = 0;
  constructor() { setTimeout(() => { this.onerror?.(); this.onclose?.({ code: 1006 }); }, 0); }
  close() {}
}

const DEMO_WORDS = /judge|replay|evaluation|round 1|seed|fingerprint|acceptance/i;
const common = { "/api/v1/status": status, "/api/monitoring/status": source };

beforeEach(() => { window.location.hash = ""; vi.stubGlobal("WebSocket", FailingSocket); });
afterEach(() => vi.unstubAllGlobals());

describe("portal access", () => {
  it("shows the sign-in page with brand and disclaimer when not signed in", async () => {
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: null } }));
    render(<App />);
    expect(await screen.findByTestId("sign-in")).toBeInTheDocument();
    expect(screen.getAllByText(/AROGYA DRISHTI/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Not for medical diagnosis/)).toBeInTheDocument();
    expect(screen.queryByTestId("patient-row")).toBeNull();
  });

  it("shows the server's error for a wrong password", async () => {
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: null },
      "/api/auth/login": { __status: 401, body: { issue: [{ diagnostics: "Incorrect username or password." }] } } }));
    render(<App />);
    fireEvent.change(await screen.findByTestId("username"), { target: { value: "doctor" } });
    fireEvent.change(screen.getByTestId("password"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("sign-in"));
    expect(await screen.findByTestId("login-error")).toHaveTextContent("Incorrect username or password.");
  });

  it("returns to sign-in when the session expires (HTTP 401)", async () => {
    window.location.hash = "#/doctor";
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: doctor },
      "/api/clinical/overview": { __status: 401, body: { issue: [{ diagnostics: "Sign in required." }] } }, "/api/alerts": { alerts: [] } }));
    render(<App />);
    expect(await screen.findByText(/Your session has ended/)).toBeInTheDocument();
  });
});

describe("Doctor Portal", () => {
  it("derives dashboard statistics from the overview and never shows NORMAL without data", async () => {
    window.location.hash = "#/doctor";
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: doctor }, "/api/clinical/overview": overview, "/api/alerts": { alerts: [] } }));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("stat-total-value")).toHaveTextContent("2"));
    expect(screen.getByTestId("stat-monitored-value")).toHaveTextContent("1");
    expect(screen.getByTestId("stat-urgent-value")).toHaveTextContent("1");
    expect(screen.getByTestId("stat-review-value")).toHaveTextContent("0");
    expect(screen.getAllByTestId("attention-row")).toHaveLength(1);
    expect(document.body.textContent).not.toMatch(DEMO_WORDS);
  });

  it("searches, filters and sorts the patient directory", async () => {
    window.location.hash = "#/doctor/patients";
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: doctor }, "/api/clinical/overview": overview }));
    render(<App />);
    await waitFor(() => expect(screen.getAllByTestId("patient-row")).toHaveLength(2));
    const rows = screen.getAllByTestId("patient-row");
    expect(within(rows[0]).getByText("Ariane Kirlin")).toBeInTheDocument();          // URGENT first
    expect(within(rows[1]).getByText("Not assessed")).toBeInTheDocument();          // no data: not NORMAL
    fireEvent.change(screen.getByTestId("search"), { target: { value: "victor" } });
    expect(screen.getAllByTestId("patient-row")).toHaveLength(1);
    fireEvent.change(screen.getByTestId("search"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("filter"), { target: { value: "URGENT" } });
    expect(screen.getAllByTestId("patient-row")).toHaveLength(1);
    expect(screen.getByTestId("result-count")).toHaveTextContent("1 of 2 patients");
  });

  it("shows the monitoring page with vitals, plain-language risk and hidden technical details", async () => {
    window.location.hash = "#/doctor/patients/p1";
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: doctor },
      "/api/patients/p1/profile": profile, "/api/alerts": { alerts: [] }, "/api/demo/monitor/p1": monitor }));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("patient-name")).toHaveTextContent("Ariane Kirlin"));
    await waitFor(() => expect(screen.getByTestId("value-heart_rate")).toHaveTextContent("134bpm"));
    expect(screen.getByTestId("vital-respiratory_rate")).toHaveTextContent("No trusted reading in this period");
    expect(screen.getByTestId("risk-level")).toHaveTextContent("URGENT");
    expect(screen.getByTestId("risk-headline")).toHaveTextContent(/urgent clinical review/);
    expect(screen.getByTestId("risk-reasons")).toHaveTextContent("NEWS2-style score 11 (partial). Contributing: Heart Rate 134 bpm (score 3)");
    // breakdown from the API's per-parameter scores; missing parameters are not invented
    expect(screen.getByTestId("news2-heart_rate")).toHaveTextContent("Heart Rate134 bpmscore 3");
    expect(screen.getByTestId("news2-spo2")).toHaveTextContent("SpO₂ (Oxygen Saturation)Not available");
    expect(screen.getByTestId("news2-total")).toHaveTextContent("Total score11 from 4 available parameters");
    expect(screen.getByTestId("news2-breakdown")).toHaveTextContent("Uses up to 4 of the 7 standard NEWS2 parameters");
    expect(within(screen.getByTestId("news2-classes")).getByText("7 or higher").closest("li")).toHaveAttribute("aria-current", "true");
    expect((screen.getByTestId("technical-details") as HTMLDetailsElement).open).toBe(false);
    expect(screen.getByTestId("sim-start")).toBeInTheDocument();
    expect(screen.getByText(/Demo \/ Simulation/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("live-mode")).toHaveTextContent("Updating every few seconds"));
  });
});

describe("Patient Portal", () => {
  it("shows only the signed-in patient's portal and redirects away from doctor pages", async () => {
    window.location.hash = "#/doctor";
    const fetchMock = routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: patientUser }, "/api/demo/monitor/p1": monitor, "/api/patients/p1/profile": profile });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await waitFor(() => expect(window.location.hash).toBe("#/me"));
    expect(await screen.findByTestId("greeting")).toHaveTextContent("Ariane");
    await waitFor(() => expect(screen.getByTestId("patient-status")).toHaveTextContent("flagged as urgent"));
    expect(screen.queryByText("Patients")).toBeNull();
    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.startsWith("/api/clinical/overview") || u.startsWith("/api/alerts") || u.startsWith("/api/monitoring/status"))).toBe(false);
    expect(urls.filter((u) => u.includes("/p")).every((u) => u.includes("/p1"))).toBe(true);
  });

  it("explains missing data plainly instead of showing a status", async () => {
    window.location.hash = "#/me";
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: patientUser },
      "/api/demo/monitor/p1": { ...monitor, observationCount: 0, assessment: { ...monitor.assessment, assessable: false, level: null, monitoringStatus: "no_recent_data", trustedVitals: 0 } } }));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("patient-status")).toHaveTextContent("No recent readings"));
  });
});

// ---------------------------------------------------------------- Phase 2/3
import { parseCsv } from "./pages/data";

const ev = (id: number, level: string, extra: Record<string, unknown> = {}) => ({
  id, patient_id: "p1", patientName: "Ariane Kirlin", created_at: now, measured_at: now, kind: "escalated", level, previous_level: "WATCH",
  vital: null, value: 5, unit: "points", rule: null, reason: "x", observation: null, summary: `Escalated to ${level}: combined early-warning score 5.`,
  read: false, acknowledgements: [], acknowledgedByMe: false, ...extra,
});

class ScriptedSocket {
  static last: ScriptedSocket | null = null;
  onmessage: ((e: { data: string }) => void) | null = null; onclose: ((e: { code: number }) => void) | null = null; onerror: (() => void) | null = null;
  readyState = 1;
  url: string;
  constructor(url: string) { this.url = url; if (url.includes("/ws/notifications")) ScriptedSocket.last = this; }
  send(m: unknown) { this.onmessage?.({ data: JSON.stringify(m) }); }
  close() {}
}

describe("Doctor notifications", () => {
  it("pops up only events newer than the connection cursor, once each, on any doctor page", async () => {
    window.location.hash = "#/doctor/alerts";
    const { FakeAudioContext } = await import("./testAudio");
    const { _resetForTests } = await import("./alertSound");
    FakeAudioContext.instances = []; vi.stubGlobal("AudioContext", FakeAudioContext); localStorage.clear(); _resetForTests();
    vi.stubGlobal("WebSocket", ScriptedSocket);
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: doctor }, "/api/clinical/overview": overview, "/api/alerts": { alerts: [] } }));
    render(<App />);
    await waitFor(() => expect(ScriptedSocket.last).not.toBeNull());
    const ws = ScriptedSocket.last!;
    fireEvent.pointerDown(document.body);                                     // user interaction unlocks audio
    await waitFor(() => expect(FakeAudioContext.instances[0]?.state).toBe("running"));
    const beeps = () => FakeAudioContext.instances[0].starts.length;
    // history at connect: shown in the bell, never as a pop-up
    ws.send({ type: "hello", cursor: 10, latestId: 10, unread: 0, items: [ev(10, "URGENT", { read: true })] });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryAllByTestId("toast")).toHaveLength(0);
    expect(beeps()).toBe(0);                                                  // history: no sound
    ws.send({ type: "events", cursor: 12, unread: 2, items: [ev(11, "REVIEW"), ev(12, "URGENT")] });
    await waitFor(() => expect(screen.getAllByTestId("toast")).toHaveLength(2));
    expect(beeps()).toBe(3);                                                  // one URGENT pattern for the batch
    ws.send({ type: "events", cursor: 12, unread: 2, items: [ev(12, "URGENT")] });   // repeated delivery
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getAllByTestId("toast")).toHaveLength(2);
    expect(beeps()).toBe(3);                                                  // repeated delivery: no sound
    fireEvent.click(screen.getByTestId("sound-toggle"));                      // mute
    expect(screen.getByTestId("sound-toggle")).toHaveAttribute("aria-pressed", "false");
    ws.send({ type: "events", cursor: 13, unread: 3, items: [ev(13, "WATCH")] });
    await waitFor(() => expect(screen.getAllByTestId("toast")).toHaveLength(3));
    expect(beeps()).toBe(3);                                                  // muted: pop-up still shown, no sound
    const urgent = screen.getAllByTestId("toast").find((t) => t.getAttribute("data-level") === "URGENT")!;
    expect(urgent).toHaveAttribute("role", "alert");
    expect(within(urgent).getByTestId("toast-patient")).toHaveTextContent("Ariane Kirlin");
    expect(screen.getByTestId("bell-count")).toHaveTextContent("3");
    fireEvent.click(within(urgent).getByLabelText("Dismiss notification"));
    expect(screen.getAllByTestId("toast")).toHaveLength(2);
    fireEvent.click(screen.getAllByTestId("toast-view")[0]);
    expect(window.location.hash).toBe("#/doctor/patients/p1");
  });
});

describe("Data management helpers", () => {
  it("parses quoted CSV and reports malformed files", () => {
    const r = parseCsv('﻿Name,birth_date,gender\r\n"O\'Neil, ""Jo""",1970-01-02,female\r\n');
    expect(r.header).toEqual(["name", "birth_date", "gender"]);
    expect(r.rows[0].name).toBe('O\'Neil, "Jo"');
    expect(parseCsv("a,b\n1\n").error).toMatch(/Row 2 has 1 values/);
    expect(parseCsv("").error).toMatch(/empty/);
    expect(parseCsv('a\n"x').error).toMatch(/unclosed/);
  });

  it("opens SparkMeet in a new tab from both portals without patient details in the URL", async () => {
    window.location.hash = "#/me/video";
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: patientUser }, "/api/demo/monitor/p1": monitor }));
    render(<App />);
    const a = await screen.findByTestId("video-patient");
    expect(a).toHaveAttribute("href", "https://sparkmeet-web.onrender.com/");
    expect(a).toHaveAttribute("target", "_blank");
    expect(a).toHaveAttribute("rel", "noopener noreferrer");
  });
});

describe("Early Detection Lab", () => {
  it("plays back the same readings on both sides and reports 'Not detected' honestly", async () => {
    window.location.hash = "#/doctor/lab";
    const step = (t: string, spo2: number, level: string, alarm = false) => ({
      t, readings: { spo2 }, latest: { spo2, heart_rate: 80, respiratory_rate: 16, body_temperature: 37 },
      comparator: { alarm, breaches: alarm ? [{ vital: "spo2", value: spo2, text: `SpO₂ ${spo2} % below 90` }] : [] },
      engine: { level, news2: level === "NORMAL" ? 0 : 1, measured: 4, alerts: level === "NORMAL" ? [] : [{ level, ruleType: "news2-parameter", vital: "spo2", vitalLabel: "SpO2", value: spo2, unit: "%", rule: "", reason: "", score: 1, baseline: null }], trend: false, suppressedNow: [] },
      spo2Baseline: 97,
    });
    const analysis = {
      comparator: { name: "Fixed-threshold comparator (demo)", description: "d", limits: {} }, engine: { name: "e", description: "d" },
      start: "2026-11-12T10:00:00Z", end: "2026-11-12T10:01:00Z",
      steps: [step("2026-11-12T10:00:00Z", 97, "NORMAL"), step("2026-11-12T10:01:00Z", 95, "WATCH")],
      firstWarning: { index: 1, t: "2026-11-12T10:01:00Z", minutesFromStart: 1, latest: {}, level: "WATCH", news2: 1, alerts: [] },
      firstTrendWarning: null, firstComparatorAlert: null, advantageMinutes: null, comparatorAlarmSteps: 0, engineAlertSteps: 1,
      artifacts: { suppressed: [], comparatorAlarmsFromArtifacts: [], engineAlertsDuringArtifacts: 0 },
    };
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: doctor },
      "/api/patients": { count: 1, patients: [{ id: "p1", name: "Ariane992 Kirlin939", source: "synthea" }] },
      "/api/early-detection/prepared": { deterioration: { runId: "r1", state: "completed", progress: 1 } },
      "/api/early-detection/runs/r1": { ready: true, session: { state: "completed", progress: 1, persisted: 8, eventsTotal: 8, scenarioName: "x", lastError: null }, analysis } }));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("lab-prepared")).toHaveTextContent("plays instantly"));
    fireEvent.click(screen.getByTestId("lab-run-early"));
    await waitFor(() => expect(screen.getByTestId("lab-engine")).toBeInTheDocument());
    expect(screen.getAllByTestId("lab-spo2").map((e) => e.textContent)).toEqual(["97%", "97%"]);   // same reading on both sides
    fireEvent.click(screen.getByTestId("lab-skip"));
    await waitFor(() => expect(screen.getByTestId("lab-summary")).toBeInTheDocument());
    expect(screen.getByTestId("lab-sum-trad")).toHaveTextContent("Not detected");
    expect(screen.getByTestId("lab-sum-engine")).toHaveTextContent("T+1 min");
    expect(screen.getByTestId("lab-advantage")).toHaveTextContent("Only AROGYA DRISHTI detected it");
    expect(screen.getByTestId("lab-disclaimer")).toHaveTextContent("Not for medical diagnosis");
  });
});

describe("Sensor Reliability Lab", () => {
  it("shows the comparator alert, the sensor-quality warning and measured results on identical readings", async () => {
    window.location.hash = "#/doctor/sensor-lab";
    const mk = (t: string, spo2: number, hr: number, alarm: boolean, flagged: boolean) => ({
      t, readings: { spo2, heart_rate: hr }, latest: { spo2, heart_rate: hr, respiratory_rate: 15, body_temperature: 36.8 },
      comparator: { alarm, breaches: alarm ? [{ vital: "spo2", value: spo2, text: `SpO₂ ${spo2} % below 90` }] : [] },
      engine: { level: "NORMAL", news2: 0, measured: 4, alerts: [], trend: false,
        suppressedNow: flagged ? [{ vital: "spo2", value: spo2, reason: "probe-off: zero reading (HR and SpO2 both 0)" }] : [] },
      spo2Baseline: 97,
    });
    const analysis = {
      comparator: { name: "c", description: "d", limits: {} }, engine: { name: "e", description: "d" },
      start: "2026-11-12T10:00:00Z", end: "2026-11-12T10:02:00Z",
      steps: [mk("2026-11-12T10:00:00Z", 97, 74, false, false), mk("2026-11-12T10:01:00Z", 0, 0, true, true), mk("2026-11-12T10:02:00Z", 97, 74, false, false)],
      firstWarning: null, firstTrendWarning: null, firstComparatorAlert: null, advantageMinutes: null, comparatorAlarmSteps: 1, engineAlertSteps: 0,
      artifacts: { suppressed: [{ vital: "spo2", value: 0, reason: "probe-off", effective: "2026-11-12T10:01:00Z" }], comparatorAlarmsFromArtifacts: [], engineAlertsDuringArtifacts: 0 },
    };
    const side = (alerts: number, falses: number, art: number | null) => ({ clinicalAlerts: alerts, falseClinicalAlerts: falses, artifactsDetected: art, episodes: alerts ? [{ index: 1, minutes: 1, false: true, artifactOnly: true, trigger: ["x"] }] : [],
      genuineDeterioration: { applicable: false, detected: null, minutes: null, level: null }, peakLevel: "NORMAL", readingsFlaggedNotLabelled: 0 });
    const metrics = { definitions: "defs", labelledArtifactReadings: 2, scenarioHasDeterioration: false, fixed: side(1, 1, null), engine: side(0, 0, 2), falseAlertsAvoided: 1 };
    vi.stubGlobal("fetch", routeFetch({ ...common, "/api/auth/me": { authRequired: true, user: doctor },
      "/api/patients": { count: 1, patients: [{ id: "p1", name: "Alex Lang", source: "synthea" }] },
      "/api/early-detection/prepared": { artifact: { runId: "r9", state: "completed", progress: 1 } },
      "/api/sensor-lab/runs/r9": { ready: true, session: { state: "completed", progress: 1, persisted: 1, eventsTotal: 1, scenarioName: "x", lastError: null }, analysis, metrics } }));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("sl-patient")).toHaveValue("p1"));
    fireEvent.click(screen.getByTestId("sl-run"));
    await waitFor(() => expect(screen.getByTestId("sl-fixed-status")).toHaveTextContent("CLINICAL ALERT"), { timeout: 3000 });
    expect(screen.getByTestId("sl-sensor-warning")).toHaveTextContent("Possible sensor disconnection detected. Oxygen readings may be unreliable. Please check the wearable device.");
    expect(screen.getByTestId("sl-engine-status")).toHaveTextContent("No clinical alert");
    expect(screen.getAllByTestId("sl-spo2").map((e) => e.textContent)).toEqual(["0%", "0%"]);
    fireEvent.click(screen.getByTestId("sl-skip"));
    await waitFor(() => expect(screen.getByTestId("sl-results")).toBeInTheDocument());
    const rows = screen.getAllByTestId("sl-row").map((r) => r.textContent);
    expect(rows[1]).toBe("False clinical alerts10");
    expect(rows[2]).toContain("Not available");
    expect(rows[3]).toContain("Not applicable");
    expect(screen.getByTestId("sl-avoided")).toHaveTextContent("1 false clinical alert avoided");
  });
});
