import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const status = {
  checkedAt: "2026-11-12T08:00:00Z",
  checkpoint: "C1",
  services: { api: { status: "ok" }, fhir: { status: "ok", isR4: true, fhirVersion: "4.0.1" }, eventStore: { status: "ok" } },
};
const patients = {
  count: 1,
  patients: [{ id: "p1", name: "Ariane992 Kirlin939", gender: "female", age: 57, lastDischarge: "2026-08-19T00:00:00Z", activeConditions: 11, activeMedications: 4 }],
};
const profile = {
  patient: { id: "p1", name: "Ariane992 Kirlin939", gender: "female", age: 57, birthDate: "1969-08-12" },
  discharge: { encounter: "Encounter/e1", discharged: "2026-08-19T00:00:00Z", facility: "Test Hospital", inpatientStays: 1 },
  activeConditions: [{ id: "c1", condition: "Essential hypertension (disorder)" }],
  activeMedications: [{ id: "m1", medication: "metoprolol succinate 100 MG" }],
  allergies: [],
};
const empty = { label: "x", unit: "/min", series: [], latest: null };
const monitor = {
  patientId: "p1",
  windowStart: "2026-11-12T08:00:00Z",
  evaluatedAt: "2026-11-12T08:01:00Z",
  observationCount: 1,
  vitals: {
    heart_rate: { label: "Heart rate", unit: "/min", series: [{ effective: "2026-11-12T08:00:30Z", value: 134, observation: "Observation/42" }], latest: { effective: "2026-11-12T08:00:30Z", value: 134, observation: "Observation/42" } },
    spo2: empty, respiratory_rate: empty, body_temperature: empty,
  },
  risk: {
    level: "URGENT",
    readingsConsidered: 1,
    label: "Prototype rules engine (Round 1 MVP). Not NEWS2.",
    summary: "Latest heart rate 134 /min meets the URGENT band (Heart rate ≥ 131 /min).",
    alerts: [{ level: "URGENT", ruleType: "threshold", vital: "heart_rate", vitalLabel: "Heart rate", value: 134, unit: "/min", rule: "Heart rate ≥ 131 /min", observation: "Observation/42", effective: "2026-11-12T08:00:30Z", reason: "Latest heart rate 134 /min meets the URGENT band (Heart rate ≥ 131 /min)." }],
  },
  fhirProof: { observation: "Observation/42", id: "42", versionId: "1", lastUpdated: "2026-11-12T08:00:31Z", hapiUrl: "http://localhost:8090/baseR4/Observation/42", readBackMatches: true, hapiValidationErrors: 0 },
  simulator: null,
};

function routeFetch(map: Record<string, unknown>) {
  return vi.fn(async (url: string) => {
    const key = Object.keys(map).find((k) => url.startsWith(k));
    if (!key) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => map[key] };
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("Round 1 dashboard", () => {
  it("always shows brand and disclaimer, even when the API is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "AROGYA DRISHTI" })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Clinical decision support only. Not for medical diagnosis.");
    await waitFor(() => expect(screen.getByTestId("fhir-status")).toHaveTextContent("API unreachable"));
  });

  it("renders patients, profile, risk, explanations and FHIR proof from the API", async () => {
    vi.stubGlobal("fetch", routeFetch({
      "/api/v1/status": status,
      "/api/patients/p1/profile": profile,
      "/api/patients": patients,
      "/api/demo/monitor/p1": monitor,
    }));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("patient-name")).toHaveTextContent("Ariane Kirlin"));
    expect(screen.getByText(/Essential hypertension/)).toBeInTheDocument();
    expect(screen.getByText(/metoprolol/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("risk-level")).toHaveTextContent("URGENT"));
    expect(screen.getAllByText(/Heart rate ≥ 131 \/min/).length).toBeGreaterThan(0);
    expect(screen.getByTestId("fhir-proof")).toHaveTextContent("Observation/42");
    expect(screen.getByTestId("fhir-status")).toHaveTextContent("HAPI FHIR R4 connected · 4.0.1");
  });

  it("shows NORMAL and an empty state when there are no observations", async () => {
    vi.stubGlobal("fetch", routeFetch({
      "/api/v1/status": status,
      "/api/patients/p1/profile": profile,
      "/api/patients": patients,
      "/api/demo/monitor/p1": { ...monitor, observationCount: 0, vitals: { heart_rate: empty, spo2: empty, respiratory_rate: empty, body_temperature: empty }, risk: { level: "NORMAL", alerts: [], readingsConsidered: 0, label: "x", summary: "No observations in this monitoring window yet." }, fhirProof: null },
    }));
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("risk-level")).toHaveTextContent("NORMAL"));
    expect(screen.getByText(/No observation stored in this monitoring window yet/)).toBeInTheDocument();
  });
});
