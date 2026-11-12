import type { Monitor, User } from "../api";
import { IconClock, IconShield } from "../components/icons";
import { patientStatus } from "../components/risk";
import { ORDER, VitalCard, VitalCharts } from "../components/vitals";
import { Card, ErrorNote, MonitoringBadge, ago, displayName, fmtDate, fmtDateTime, tidyCondition } from "../components/ui";
import { useProfile } from "../monitor";

const TONE = {
  ok: "border-teal-200 bg-teal-50 text-teal-900",
  info: "border-sky-200 bg-sky-50 text-sky-900",
  warn: "border-orange-200 bg-orange-50 text-orange-900",
  alert: "border-red-300 bg-red-50 text-red-900",
  muted: "border-slate-200 bg-white text-navy-900",
} as const;

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

const firstName = (n: string) => displayName(n).split(" ")[0] || n;

export function MyHealth({ user, monitor, live }: { user: User; monitor: Monitor | null; live: string }) {
  const s = patientStatus(monitor);
  const last = monitor?.assessment.lastObservationAt;
  const simulated = (monitor?.assessment.sources ?? []).some((x) => /simulated/i.test(x));
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-navy-900" data-testid="greeting">{greeting()}, {firstName(user.displayName)}</h2>
        <p className="mt-1 text-sm text-navy-500">Here is a summary of your latest home monitoring readings.</p>
      </div>
      <section className={`rounded-2xl border p-5 shadow-sm ${TONE[s.tone]}`} data-testid="patient-status" aria-live="polite">
        <p className="text-lg font-semibold">{s.title}</p>
        {s.body && <p className="mt-1 text-sm">{s.body}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs opacity-90">
          <span className="inline-flex items-center gap-1.5"><IconClock width={14} height={14} />Last measurement: {last ? `${fmtDateTime(last)} (${ago(last)})` : "none recently"}</span>
          {monitor && <MonitoringBadge status={monitor.assessment.monitoringStatus} />}
          <span data-testid="live-mode">{live === "websocket" ? "Live updates on" : live === "polling" ? "Updating every few seconds" : "Connecting…"}</span>
        </div>
      </section>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {ORDER.map((k) => <VitalCard key={k} k={k} monitor={monitor} />)}
      </div>
      <Card title="About these readings">
        <ul className="space-y-1.5 text-sm text-navy-700">
          <li>Readings come from your monitoring source and are stored in your health record as they arrive{simulated ? ". The current readings are simulated for demonstration, not from a real device" : ""}.</li>
          <li>Your care team sees the same readings on their dashboard. This page does not give a diagnosis.</li>
          <li>If you feel unwell, contact your care team or call your local emergency number. Do not wait for this page to change.</li>
        </ul>
      </Card>
    </div>
  );
}

export function MyTrends({ monitor }: { monitor: Monitor | null }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-navy-500">Your readings over the monitoring period shown. Hover or tap a line to see the exact value and time.</p>
      <VitalCharts monitor={monitor} />
    </div>
  );
}

export function MyRecords({ pid }: { pid: string }) {
  const { profile, error } = useProfile(pid);
  if (error) return <ErrorNote>Could not load your record: {error}</ErrorNote>;
  if (!profile) return <p className="text-sm text-navy-500">Loading your record…</p>;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Personal details">
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm" data-testid="demographics">
          <dt className="text-navy-500">Name</dt><dd className="font-medium">{displayName(profile.patient.name)}</dd>
          <dt className="text-navy-500">Date of birth</dt><dd>{fmtDate(profile.patient.birthDate)} ({profile.patient.age} years)</dd>
          <dt className="text-navy-500">Gender</dt><dd className="capitalize">{profile.patient.gender ?? "—"}</dd>
        </dl>
      </Card>
      <Card title="Hospital discharge">
        {profile.discharge ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-navy-500">Discharged</dt><dd className="font-medium" data-testid="discharge-date">{fmtDate(profile.discharge.discharged)}</dd>
            <dt className="text-navy-500">Admitted</dt><dd>{fmtDate(profile.discharge.admitted)}</dd>
            {profile.discharge.facility && <><dt className="text-navy-500">Hospital</dt><dd className="capitalize">{profile.discharge.facility.toLowerCase()}</dd></>}
          </dl>
        ) : <p className="text-sm text-navy-500">No hospital discharge is recorded.</p>}
      </Card>
      <Card title={`Conditions (${profile.activeConditions.length})`}>
        <ul className="space-y-1 text-sm" data-testid="conditions">{profile.activeConditions.map((c) => <li key={c.id}>{tidyCondition(c.condition)}{c.onset ? <span className="text-navy-500"> · since {fmtDate(c.onset)}</span> : null}</li>)}</ul>
      </Card>
      <Card title={`Medications (${profile.activeMedications.length})`}>
        <ul className="space-y-1 text-sm" data-testid="medications">{profile.activeMedications.map((m) => <li key={m.id}>{m.medication}{m.dosage ? <span className="text-navy-500"> · {m.dosage}</span> : null}</li>)}</ul>
        {profile.allergies.length > 0 && <p className="mt-3 text-sm text-navy-700">Allergies: {profile.allergies.map((a) => a.substance).join(", ")}</p>}
      </Card>
      <p className="text-xs text-navy-500 lg:col-span-2">This is a synthetic record generated for the prototype (Synthea); it does not describe a real person.</p>
    </div>
  );
}

export function MyProfile({ user, pid, monitor }: { user: User; pid: string; monitor: Monitor | null }) {
  const { profile } = useProfile(pid);
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Account">
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-navy-500">Name</dt><dd className="font-medium">{profile ? displayName(profile.patient.name) : user.displayName}</dd>
          <dt className="text-navy-500">Username</dt><dd>{user.username}</dd>
          <dt className="text-navy-500">Age</dt><dd>{profile?.patient.age ?? "—"}</dd>
          <dt className="text-navy-500">Assigned clinician</dt><dd data-testid="clinician">Not recorded in your health record</dd>
        </dl>
      </Card>
      <Card title="Monitoring">
        <div className="space-y-2 text-sm text-navy-700">
          {monitor ? <MonitoringBadge status={monitor.assessment.monitoringStatus} /> : <span>Loading…</span>}
          <p>Last measurement: {monitor?.assessment.lastObservationAt ? fmtDateTime(monitor.assessment.lastObservationAt) : "none recently"}</p>
          <p>Source: {monitor?.assessment.sources?.join(", ") || "no source is currently sending readings"}</p>
        </div>
      </Card>
      <Card title="Privacy" className="lg:col-span-2">
        <p className="flex items-start gap-2 text-sm text-navy-700"><IconShield className="mt-0.5 shrink-0 text-teal-700" />
          Your account can only open your own record. The server checks this on every request; other patients' records are not accessible from this account.</p>
      </Card>
    </div>
  );
}
