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
  fhirProof?: { observation: string; id: string; versionId?: string; lastUpdated?: string; readBackMatches: boolean | null } | null;
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
  patientName?: string | null;
  summary?: string;
  read?: boolean;
  acknowledgements?: { username: string; acknowledgedAt: string }[];
  acknowledgedByMe?: boolean;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

// Called when the server says the session is missing or expired (HTTP 401), so the app can show sign-in.
let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: (() => void) | null) => { onUnauthorized = fn; };

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, { credentials: "same-origin", ...init });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const msg = body?.issue?.[0]?.diagnostics ?? body?.detail ?? `HTTP ${resp.status}`;
    if (resp.status === 401 && !url.startsWith("/api/auth/")) onUnauthorized?.();
    throw new ApiError(typeof msg === "string" ? msg : JSON.stringify(msg), resp.status);
  }
  return body as T;
}

const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const enc = encodeURIComponent;

export interface User { username: string; role: "doctor" | "patient"; patientId: string | null; displayName: string }
export const fetchMe = () => getJson<{ authRequired: boolean; user: User | null }>("/api/auth/me");
export const login = (username: string, password: string) => getJson<{ user: User }>("/api/auth/login", post({ username, password }));
export const logout = () => getJson<{ signedOut: boolean }>("/api/auth/logout", post({}));

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

// ---------------------------------------------------------------- doctor notifications (recorded risk events)
export interface NotificationFeed { latestId: number; baselineId: number; unread: number; items: AlertEvent[] }
export const fetchNotifications = (after?: number, limit = 30) =>
  getJson<NotificationFeed>(`/api/notifications?limit=${limit}${after !== undefined ? `&after=${after}` : ""}`);
export const markNotificationsRead = (ids: number[]) => getJson<{ marked: number; unread: number }>("/api/notifications/read", post({ ids }));
export const markAllNotificationsRead = () => getJson<{ marked: number; unread: number }>("/api/notifications/read-all", post({}));
export const acknowledgeAlert = (id: number) => getJson<{ eventId: number; username: string; acknowledgedAt: string }>(`/api/alerts/${id}/acknowledge`, post({}));
export const notificationsSocketUrl = (after?: number) =>
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/notifications${after !== undefined ? `?after=${after}` : ""}`;

// ---------------------------------------------------------------- patient management (doctor only)
export interface FieldError { row: number | null; field: string | null; message: string }
export interface NewPatient { name: string; birthDate: string; gender: string; dischargeDate?: string; phone?: string; email?: string; requestId: string; allowDuplicate?: boolean }
export class FormError extends Error { constructor(message: string, public errors: FieldError[], public status: number, public duplicateOf?: string) { super(message); } }

async function postForm<T>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(url, { credentials: "same-origin", ...post(body) });
  const data = await resp.json().catch(() => ({}));
  if (resp.status === 401) onUnauthorized?.();
  if (!resp.ok) {
    const errs: FieldError[] = data?.errors ?? [{ row: null, field: null, message: data?.issue?.[0]?.diagnostics ?? (typeof data?.detail === "string" ? data.detail : `Request failed (HTTP ${resp.status})`) }];
    throw new FormError(errs[0]?.message ?? `HTTP ${resp.status}`, errs, resp.status, data?.duplicateOf);
  }
  return data as T;
}
export const createPatient = (p: NewPatient) => postForm<{ created: true; id: string; name: string }>("/api/patients", p);
export const fetchPatientAccount = (pid: string) => getJson<{ patientId: string; hasAccount: boolean; username: string | null }>(`/api/patients/${enc(pid)}/account`);
export const provisionPatientAccount = (pid: string, reset = false) =>
  postForm<{ username: string; password: string; reset: boolean; note: string }>(`/api/patients/${enc(pid)}/account`, { reset });

export interface ImportResult {
  valid: boolean; ready?: number; imported: number; rejected: number; errors: FieldError[]; message?: string;
  results?: { row: number; ok: boolean; id: string | null; error: string | null; name?: string; patientId?: string; loinc?: string }[];
}
export const importCsv = (kind: "patients" | "observations", rows: Record<string, string>[], confirm: boolean, fileName: string, importId: string) =>
  postForm<ImportResult>(`/api/import/${kind}`, { rows, confirm, fileName, importId });

export const exportUrls = {
  directory: "/api/export/patients.csv",
  record: (pid: string) => `/api/export/patients/${enc(pid)}/record.csv`,
  observations: (pid: string) => `/api/export/patients/${enc(pid)}/observations.csv`,
};

// ---------------------------------------------------------------- Early Detection Lab (doctor only)
export interface LabAlert { level: RiskLevel; ruleType: string; vital: VitalKey | null; vitalLabel: string; value: number; unit: string; rule: string; reason: string; score?: number; baseline: { median: number; mad: number; n: number } | null }
export interface LabStep {
  t: string; readings: Partial<Record<VitalKey, number>>; latest: Partial<Record<VitalKey, number>>;
  comparator: { alarm: boolean; breaches: { vital: VitalKey; value: number; text: string }[] };
  engine: { level: RiskLevel; news2: number; measured: number; alerts: LabAlert[]; trend: boolean; suppressedNow: { vital: VitalKey; value: number; reason: string }[] };
  spo2Baseline: number | null;
}
export interface LabMarker { index: number; t: string; minutesFromStart: number; latest: Partial<Record<VitalKey, number>>; level?: RiskLevel; news2?: number; alerts?: LabAlert[]; breaches?: { vital: VitalKey; value: number; text: string }[] }
export interface LabAnalysis {
  comparator: { name: string; description: string; limits: Record<string, { low?: number; high?: number }> };
  engine: { name: string; description: string };
  start: string; end: string; steps: LabStep[];
  firstWarning: LabMarker | null; firstTrendWarning: LabMarker | null; firstComparatorAlert: LabMarker | null; advantageMinutes: number | null;
  comparatorAlarmSteps: number; engineAlertSteps: number;
  artifacts: { suppressed: { vital: VitalKey; value: number; reason: string; effective: string }[]; comparatorAlarmsFromArtifacts: { vital: VitalKey; value: number; text: string; t: string; reason: string }[]; engineAlertsDuringArtifacts: number };
}
export interface LabRun { ready: boolean; session: { state: string; progress: number; persisted: number; eventsTotal: number; scenarioName: string; lastError: string | null }; analysis?: LabAnalysis }
export type LabScenario = "deterioration" | "artifact";
export const startLabRun = (patientId: string, scenario: LabScenario) => getJson<{ runId: string }>("/api/early-detection/runs", post({ patientId, scenario }));
export const fetchLabRun = (runId: string) => getJson<LabRun>(`/api/early-detection/runs/${enc(runId)}`);
export const fetchLabPrepared = (patientId: string) =>
  getJson<Partial<Record<LabScenario, { runId: string; state: string; progress: number }>>>(`/api/early-detection/prepared?patientId=${enc(patientId)}`);
export const fetchPatientList = () => getJson<{ count: number; patients: { id: string; name: string; source?: string }[] }>("/api/patients");

// ---------------------------------------------------------------- Sensor Reliability Lab (doctor only)
export interface SensorEpisode { index: number; minutes: number; false: boolean; artifactOnly: boolean; trigger: string[]; level?: RiskLevel }
export interface SensorSide {
  clinicalAlerts: number; falseClinicalAlerts: number; artifactsDetected: number | null; episodes: SensorEpisode[];
  genuineDeterioration: { applicable: boolean; detected: boolean | null; minutes: number | null; level: RiskLevel | null };
  alarmReadings?: number; peakLevel?: RiskLevel; readingsFlaggedNotLabelled?: number;
}
export interface SensorMetrics { definitions: string; labelledArtifactReadings: number; scenarioHasDeterioration: boolean; fixed: SensorSide; engine: SensorSide; falseAlertsAvoided: number }
export interface SensorLabRun { ready: boolean; session: LabRun["session"]; analysis?: LabAnalysis; metrics?: SensorMetrics; scenario?: string }
export const fetchSensorLabRun = (runId: string) => getJson<SensorLabRun>(`/api/sensor-lab/runs/${enc(runId)}`);
