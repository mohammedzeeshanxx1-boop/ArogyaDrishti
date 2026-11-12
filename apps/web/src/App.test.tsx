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

function routeFetch(map: Record<string, unknown>) {
  return vi.fn(async (url: string) => {
    const key = Object.keys(map).find((k) => url.startsWith(k));
    if (!key) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => map[key] };
  });
}

class FailingSocket {
  onmessage: unknown = null; onerror: (() => void) | null = null; onclose: (() => void) | null = null;
  constructor() { setTimeout(() => this.onerror?.(), 0); }
  close() {}
}

const DEMO_WORDS = /judge|demonstrate|replay|evaluation|round 1|seed|fingerprint|acceptance/i;

beforeEach(() => { window.location.hash = ""; vi.stubGlobal("WebSocket", FailingSocket); });
afterEach(() => vi.unstubAllGlobals());

describe("clinician dashboard", () => {
  it("shows brand, subtitle and disclosures even when the backend is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "AROGYA DRISHTI" })).toBeInTheDocument();
    expect(screen.getByText("Personalized Post-Discharge Patient Monitoring")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/Clinical decision support only.*synthetic patients.*not clinically validated/);
    await waitFor(() => expect(screen.getByTestId("status-api")).toHaveTextContent("Unreachable"));
  });

  it("lists patients from the API and never shows NORMAL without data", async () => {
    vi.stubGlobal("fetch", routeFetch({ "/api/v1/status": status, "/api/monitoring/status": source, "/api/clinical/overview": overview, "/api/alerts": { alerts: [] } }));
    render(<App />);
    const cards = await screen.findAllByTestId("patient-card");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText("Ariane Kirlin")).toBeInTheDocument();
    expect(within(cards[0]).getByText("URGENT")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Not assessed")).toBeInTheDocument();
    expect(within(cards[1]).getByText("No recent data")).toBeInTheDocument();
    expect(within(cards[1]).queryByText("NORMAL")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("status-fhir")).toHaveTextContent("Connected (R4 4.0.1)"));
    expect(screen.getByTestId("status-source")).toHaveTextContent("simulated source");
    expect(document.body.textContent).not.toMatch(DEMO_WORDS);
  });

  it("filters by risk and searches by name", async () => {
    vi.stubGlobal("fetch", routeFetch({ "/api/v1/status": status, "/api/monitoring/status": source, "/api/clinical/overview": overview, "/api/alerts": { alerts: [] } }));
    render(<App />);
    await screen.findAllByTestId("patient-card");
    fireEvent.click(screen.getByRole("button", { name: /Not assessed/ }));
    expect(screen.getAllByTestId("patient-card")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /^All$/ }));
    fireEvent.change(screen.getByPlaceholderText("Search by name"), { target: { value: "victor" } });
    expect(screen.getAllByTestId("patient-card")).toHaveLength(1);
  });

  it("shows the patient detail with risk reasons, baseline and polling fallback", async () => {
    window.location.hash = "#/patient/p1";
    vi.stubGlobal("fetch", routeFetch({
      "/api/v1/status": status, "/api/monitoring/status": source, "/api/patients/p1/profile": profile,
      "/api/demo/monitor/p1": monitor, "/api/alerts": { alerts: [] },
    }));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("patient-name")).toHaveTextContent("Ariane Kirlin"));
    expect(screen.getByText("Ischemic heart disease")).toBeInTheDocument();
    expect(screen.getByText(/clopidogrel/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("risk-level")).toHaveTextContent("URGENT"));
    expect(screen.getByTestId("risk-reasons")).toHaveTextContent("NEWS2-style partial aggregate 11.");
    expect(screen.getByText(/Partial NEWS2-style score/)).toBeInTheDocument();
    expect(screen.getByTestId("vital-heart_rate")).toHaveTextContent("Personal baseline 76 /min (+58)");
    await waitFor(() => expect(screen.getByTestId("live-mode")).toHaveTextContent("Updating every few seconds"));
    expect(document.body.textContent).not.toMatch(DEMO_WORDS);
  });

  it("shows an honest empty state when a patient has no readings", async () => {
    window.location.hash = "#/patient/p1";
    const empty = { label: "x", unit: "/min", series: [], latest: null };
    vi.stubGlobal("fetch", routeFetch({
      "/api/v1/status": status, "/api/monitoring/status": { ...source, status: "none", lastIngestionAt: null },
      "/api/patients/p1/profile": profile, "/api/alerts": { alerts: [] },
      "/api/demo/monitor/p1": { ...monitor, observationCount: 0, windowStart: new Date(Date.now() - 3600_000).toISOString(),
        vitals: { heart_rate: empty, spo2: empty, respiratory_rate: empty, body_temperature: empty },
        risk: { ...monitor.risk, level: "NORMAL", alerts: [], news2: { ...monitor.risk.news2, total: 0, parameters: {} } },
        assessment: { ...monitor.assessment, assessable: false, level: null, monitoringStatus: "no_recent_data", trustedVitals: 0, sources: [] } },
    }));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("risk-not-assessed")).toHaveTextContent("Risk is not assessed without data"));
    expect(screen.queryByTestId("risk-level")).toBeNull();
    expect(screen.getByText(/No vital-sign readings received/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("status-source")).toHaveTextContent("No source connected"));
  });

  it("starts a simulation from the patient page and shows the waiting state for the new run", async () => {
    window.location.hash = "#/patient/p1";
    const empty = { label: "x", unit: "/min", series: [], latest: null };
    const sim = { running: true, runId: "r1", patientId: "p1", scenario: "deterioration", scenarioLabel: "Gradual Deterioration",
      step: 0, totalSteps: 20, intervalSeconds: 2, startedAt: now, finishedAt: null, stopped: false, accepted: 0, rejected: 0, lastError: null, lastObservationId: null };
    const fetchMock = routeFetch({
      "/api/v1/status": status, "/api/monitoring/status": source,
      "/api/patients/p1/profile": profile, "/api/alerts": { alerts: [] },
      "/api/demo/simulator/start": sim,
      "/api/demo/monitor/p1": { ...monitor, observationCount: 0, windowStart: now, simulator: sim,
        vitals: { heart_rate: empty, spo2: empty, respiratory_rate: empty, body_temperature: empty },
        risk: { ...monitor.risk, level: "NORMAL", alerts: [], news2: { ...monitor.risk.news2, total: 0, parameters: {} } },
        assessment: { ...monitor.assessment, assessable: false, level: null, monitoringStatus: "no_recent_data", trustedVitals: 0, sources: [] } },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("sim-status")).toHaveTextContent("Running"));
    expect(screen.getByTestId("waiting")).toHaveTextContent("Waiting for readings");
    expect(screen.getByTestId("sim-progress")).toHaveTextContent("step 0 of 20");
    expect(screen.queryByTestId("risk-level")).toBeNull();
    expect(screen.getByTestId("sim-start")).toBeDisabled();
    fireEvent.click(screen.getByTestId("sim-reset"));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/demo/reset"))).toBe(true));
  });
});
