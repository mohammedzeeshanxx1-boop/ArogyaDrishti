export type ServiceState = "ok" | "unreachable" | "error" | "checking";
export type RiskLevel = "NORMAL" | "WATCH" | "REVIEW" | "URGENT";
export type VitalKey = "heart_rate" | "spo2" | "respiratory_rate" | "body_temperature";

export interface StatusResponse {
  checkedAt: string;
  checkpoint: string;
  services: {
    api: { status: ServiceState; version?: string };
    fhir: { status: ServiceState; url?: string; fhirVersion?: string; isR4?: boolean; software?: string; detail?: string };
    eventStore: { status: ServiceState; schemaVersion?: number; detail?: string };
  };
}

export interface PatientSummary {
  id: string;
  name: string;
  gender?: string;
  birthDate?: string;
  age?: number;
  lastDischarge?: string;
  activeConditions: number;
  activeMedications: number;
}

export interface PatientProfile {
  patient: { id: string; name: string; gender?: string; birthDate?: string; age?: number; syntheaId?: string };
  discharge: { encounter: string; type?: string; admitted?: string; discharged?: string; facility?: string; inpatientStays: number } | null;
  activeConditions: { id: string; condition?: string; onset?: string }[];
  activeMedications: { id: string; medication?: string; authoredOn?: string }[];
  allergies: { id: string; substance?: string }[];
}

export interface Point {
  effective: string;
  value: number;
  observation: string;
}

export interface Alert {
  level: RiskLevel;
  ruleType: "threshold" | "trend" | "multi-parameter";
  vital: VitalKey | null;
  vitalLabel: string;
  value: number;
  unit: string;
  rule: string;
  observation: string;
  effective: string;
  reason: string;
}

export interface SimulatorState {
  running: boolean;
  runId: string | null;
  patientId: string | null;
  scenario: "stable" | "deterioration" | null;
  scenarioLabel: string | null;
  step: number;
  totalSteps: number;
  intervalSeconds: number;
  startedAt: string | null;
  finishedAt: string | null;
  stopped: boolean;
  accepted: number;
  rejected: number;
  lastError: string | null;
  lastObservationId: string | null;
}

export interface FhirProof {
  observation: string;
  id: string;
  versionId?: string;
  lastUpdated?: string;
  hapiUrl: string;
  readBackMatches: boolean | null;
  hapiValidationErrors: number | null;
  replay?: { sessionId: string; seq: number; batch: number; persistStatus: string; measuredAt: string; ingestedAt: string; validation: string } | null;
}

export type ReplayState = "created" | "running" | "paused" | "stopped" | "completed" | "error";
export type ReplaySpeed = "1x" | "5x" | "10x" | "batch";

export interface ReplaySession {
  sessionId: string;
  patientId: string;
  source: string;
  description: string;
  scenario: string | null;
  scenarioName: string | null;
  seed: number | null;
  durationMinutes: number | null;
  intervalSeconds: number | null;
  speed: ReplaySpeed;
  state: ReplayState;
  anchor: string;
  endsAt: string;
  simulatedNow: string;
  eventsTotal: number;
  cursor: number;
  persisted: number;
  created: number;
  existing: number;
  progress: number;
  batches: number;
  failedBatches: number;
  lastError: string | null;
  fingerprint: string;
  resetFrom: string | null;
}

export interface Monitor {
  patientId: string;
  windowStart: string;
  evaluatedAt: string;
  observationCount: number;
  vitals: Record<VitalKey, { label: string; unit: string; series: Point[]; latest: Point | null }>;
  risk: { level: RiskLevel; alerts: Alert[]; readingsConsidered: number; label: string; summary: string };
  fhirProof: FhirProof | null;
  simulator: SimulatorState | null;
  replay: ReplaySession | null;
  truncated?: boolean;
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const msg = body?.issue?.[0]?.diagnostics ?? body?.detail ?? `HTTP ${resp.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return body as T;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const fetchStatus = () => getJson<StatusResponse>("/api/v1/status");
export const fetchPatients = () => getJson<{ count: number; patients: PatientSummary[] }>("/api/patients");
export const fetchProfile = (id: string) => getJson<PatientProfile>(`/api/patients/${encodeURIComponent(id)}/profile`);
export const fetchMonitor = (id: string) => getJson<Monitor>(`/api/demo/monitor/${encodeURIComponent(id)}`);
export const fetchObservation = (id: string) => getJson<Record<string, any>>(`/api/fhir/Observation/${encodeURIComponent(id)}`);
export const startScenario = (patientId: string, scenario: "stable" | "deterioration") =>
  getJson<SimulatorState>("/api/demo/simulator/start", post({ patientId, scenario }));
export const stopScenario = () => getJson<SimulatorState>("/api/demo/simulator/stop", post({}));
export const resetDemo = (patientId: string) => getJson<{ windowStart: string }>("/api/demo/reset", post({ patientId }));

export const createReplay = (body: { patientId: string; scenario: string; speed: ReplaySpeed; durationMinutes: number; intervalSeconds?: number }) =>
  getJson<ReplaySession>("/api/replay/sessions", post(body));
export const replayAction = (sessionId: string, action: "start" | "pause" | "resume" | "stop" | "reset") =>
  getJson<ReplaySession>(`/api/replay/sessions/${encodeURIComponent(sessionId)}/${action}`, post({}));
