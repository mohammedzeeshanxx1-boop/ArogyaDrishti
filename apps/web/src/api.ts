export type ServiceState = "ok" | "unreachable" | "error" | "checking";
export type RiskLevel = "NORMAL" | "WATCH" | "REVIEW" | "URGENT";
export type VitalKey = "heart_rate" | "spo2" | "respiratory_rate" | "body_temperature";
export type MonitoringStatus = "active" | "stale" | "no_recent_data" | "unavailable";

export interface StatusResponse {
  checkedAt: string;
  services: {
    api: { status: ServiceState; version?: string };
    fhir: { status: ServiceState; fhirVersion?: string; isR4?: boolean; software?: string; detail?: string };
    eventStore: { status: ServiceState };
  };
}

export interface MonitoringSourceStatus {
  status: "receiving" | "idle" | "none";
  lastIngestionAt: string | null;
  secondsSinceLastIngestion: number | null;
  latestSourceLabel: string | null;
  simulatedSourcesRunning: string[];
  physicalDevicesConnected: number;
}

export interface Baseline { median: number; mad: number; n: number; from: string; to: string }

export interface PatientMonitoring {
  assessable: boolean;
  level: RiskLevel | null;
  monitoringStatus: MonitoringStatus;
  lastObservationAt: string | null;
  trustedVitals: number;
  requiredTrustedVitals: number;
  recentWindowMinutes: number;
  staleAfterMinutes: number;
  sources?: string[];
  latest: Partial<Record<VitalKey, { value: number; effective: string; observation: string; score: number; baseline: Baseline | null }>>;
  topReason?: string | null;
  spo2Scale?: number;
}

export interface OverviewPatient {
  id: string;
  name: string;
  gender?: string;
  birthDate?: string;
  age?: number;
  lastDischarge?: string;
  activeConditions: number;
  activeMedications: number;
  monitoring: PatientMonitoring;
}

export interface Overview { generatedAt: string; recentWindowMinutes: number; staleAfterMinutes: number; patients: OverviewPatient[] }

export interface PatientProfile {
  patient: { id: string; name: string; gender?: string; birthDate?: string; age?: number };
  discharge: { encounter: string; type?: string; admitted?: string; discharged?: string; facility?: string; reason?: string[]; inpatientStays: number } | null;
  activeConditions: { id: string; condition?: string; onset?: string }[];
  activeMedications: { id: string; medication?: string; authoredOn?: string; dosage?: string }[];
  allergies: { id: string; substance?: string; criticality?: string }[];
}

export interface Point { effective: string; value: number; observation: string }

export interface Alert {
  level: RiskLevel;
  ruleType: string;
  vital: VitalKey | null;
  vitalLabel: string;
  value: number;
  unit: string;
  rule: string;
  observation: string;
  effective: string;
  reason: string;
  score?: number;
  baseline?: Baseline;
}

export interface Scale2Status {
  patientId: string; scale: number; eligible: boolean; rule: string;
  flag: { id: string; reference: string; author?: string; reason?: string; since?: string } | null;
  supportingConditions: string[];
}

export interface Monitor {
  patientId: string;
  windowStart: string;
  evaluatedAt: string;
  observationCount: number;
  vitals: Record<VitalKey, { label: string; unit: string; series: Point[]; latest: Point | null }>;
  risk: {
    level: RiskLevel; alerts: Alert[]; readingsConsidered: number; label: string; summary: string;
    suppressed: { vital: string; value: number; observation: string; effective: string; reason: string }[];
    suppressedCount: number;
    news2: { total: number; level: RiskLevel; measuredParameters: number; of: number; partial: boolean; spo2Scale: number; notAvailable: string[];
      parameters: Partial<Record<VitalKey, { score: number; value: number; observation: string; effective: string; bands: string; baseline: Baseline | null }>> };
  };
  assessment: PatientMonitoring;
  scale2?: Scale2Status;
  simulator?: SimulatorState | null;
}

export interface SimulatorState {
  running: boolean; runId: string | null; patientId: string | null; scenario: string | null; scenarioLabel: string | null;
  step: number; totalSteps: number; intervalSeconds: number; startedAt: string | null; finishedAt: string | null;
  stopped: boolean; accepted: number; rejected: number; lastError: string | null; lastObservationId: string | null;
}

export interface AlertEvent {
  id: number;
  patient_id: string;
  created_at: string;
  measured_at: string | null;
  kind: "raised" | "escalated" | "de-escalated" | "resolved";
  level: RiskLevel;
  previous_level: RiskLevel | null;
  vital: VitalKey | null;
  value: number | null;
  unit: string | null;
  rule: string | null;
  reason: string;
  observation: string | null;
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

const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const enc = encodeURIComponent;

export const fetchStatus = () => getJson<StatusResponse>("/api/v1/status");
export const fetchMonitoringStatus = () => getJson<MonitoringSourceStatus>("/api/monitoring/status");
export const fetchOverview = () => getJson<Overview>("/api/clinical/overview");
export const fetchProfile = (pid: string) => getJson<PatientProfile>(`/api/patients/${enc(pid)}/profile`);
export const fetchMonitor = (pid: string) => getJson<Monitor>(`/api/demo/monitor/${enc(pid)}`);
export const fetchAlerts = (pid?: string, limit = 50) =>
  getJson<{ alerts: AlertEvent[] }>(`/api/alerts?limit=${limit}${pid ? `&patient=${enc(pid)}` : ""}`);
export const setScale2 = (pid: string, prescribedBy: string, reason: string) =>
  getJson<Scale2Status>(`/api/patients/${enc(pid)}/scale2`, post({ prescribedBy, reason }));
export const clearScale2 = (pid: string) => getJson<Scale2Status>(`/api/patients/${enc(pid)}/scale2`, { method: "DELETE" });
export const monitorSocketUrl = (pid: string) =>
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/monitor/${enc(pid)}?mode=personalized`;

// Simulated monitoring source (development and demonstration). Readings go through the normal ingestion pipeline.
export const SCENARIOS = [
  { id: "stable", label: "Stable Recovery" },
  { id: "deterioration", label: "Gradual Deterioration" },
] as const;
export const fetchSimulator = () => getJson<SimulatorState>("/api/demo/simulator");
export const startSimulation = (patientId: string, scenario: string) => getJson<SimulatorState>("/api/demo/simulator/start", post({ patientId, scenario }));
export const stopSimulation = () => getJson<SimulatorState>("/api/demo/simulator/stop", post({}));
export const resetSimulation = (patientId: string) => getJson<{ windowStart: string; simulator: SimulatorState }>("/api/demo/reset", post({ patientId }));
