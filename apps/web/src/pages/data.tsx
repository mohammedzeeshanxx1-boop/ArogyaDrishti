import { useEffect, useMemo, useRef, useState } from "react";
import {
  FormError, createPatient, exportUrls, fetchPatientAccount, importCsv, provisionPatientAccount,
  type FieldError, type ImportResult,
} from "../api";
import { IconCheck, IconDownload, IconExternal, IconPlus, IconUpload, IconVideo } from "../components/icons";
import { Card, ErrorNote, displayName } from "../components/ui";
import { SPARKMEET_URL } from "../brand";
import { useOverview } from "./doctor";

const newId = () => (crypto?.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

/** RFC 4180 CSV parser (quoted fields, embedded commas/quotes/newlines, CRLF, UTF-8 BOM). */
export function parseCsv(text: string): { header: string[]; rows: Record<string, string>[]; error?: string } {
  const src = text.replace(/^﻿/, "");
  const records: string[][] = [];
  let field = "", rec: string[] = [], q = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (q) {
      if (ch === '"' && src[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') q = false;
      else field += ch;
    } else if (ch === '"' && field === "") q = true;
    else if (ch === ",") { rec.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i++;
      rec.push(field); field = "";
      if (rec.some((c) => c.trim() !== "")) records.push(rec);
      rec = [];
    } else field += ch;
  }
  if (q) return { header: [], rows: [], error: "The file has an unclosed quoted field." };
  rec.push(field);
  if (rec.some((c) => c.trim() !== "")) records.push(rec);
  if (records.length === 0) return { header: [], rows: [], error: "The file is empty." };
  const header = records[0].map((h) => h.trim().toLowerCase());
  const dup = header.find((h, i) => h && header.indexOf(h) !== i);
  if (dup) return { header, rows: [], error: `Column "${dup}" appears twice.` };
  const bad = records.findIndex((r, i) => i > 0 && r.length !== header.length);
  if (bad > 0) return { header, rows: [], error: `Row ${bad + 1} has ${records[bad].length} values but the header has ${header.length} columns.` };
  return { header, rows: records.slice(1).map((r) => Object.fromEntries(header.map((h, i) => [h, r[i].trim()]))) };
}

function Field({ label, children, hint, error }: { label: string; children: React.ReactNode; hint?: string; error?: string }) {
  return (
    <label className="block text-sm font-medium text-navy-700">{label}
      <div className="mt-1">{children}</div>
      {hint && !error && <span className="mt-1 block text-xs font-normal text-navy-500">{hint}</span>}
      {error && <span className="mt-1 block text-xs font-medium text-red-700" role="alert">{error}</span>}
    </label>
  );
}
const input = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm";
const btn = "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold shadow-sm disabled:cursor-not-allowed disabled:opacity-50";

function Credentials({ pid, onDone }: { pid: string; onDone?: () => void }) {
  const [state, setState] = useState<{ hasAccount: boolean; username: string | null } | null>(null);
  const [cred, setCred] = useState<{ username: string; password: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  useEffect(() => { setCred(null); setErr(null); setConfirmReset(false); fetchPatientAccount(pid).then(setState).catch((e) => setErr(String(e?.message ?? e))); }, [pid]);
  const run = async (reset: boolean) => {
    setBusy(true); setErr(null);
    try { const r = await provisionPatientAccount(pid, reset); setCred(r); setState({ hasAccount: true, username: r.username }); setConfirmReset(false); onDone?.(); }
    catch (e: any) { setErr(String(e?.message ?? e)); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-3" data-testid="credentials">
      {state === null && !err && <p className="text-sm text-navy-500">Checking login…</p>}
      {state && !cred && (state.hasAccount
        ? <div className="flex flex-wrap items-center gap-3 text-sm"><span>Login: <strong>{state.username}</strong></span>
            {!confirmReset ? <button type="button" className={`${btn} border border-slate-300 bg-white text-navy-900`} onClick={() => setConfirmReset(true)}>Issue new password</button>
              : <span className="flex items-center gap-2"><span className="text-xs text-navy-700">The current password stops working.</span>
                  <button type="button" disabled={busy} className={`${btn} bg-navy-900 text-white`} onClick={() => run(true)}>Confirm</button>
                  <button type="button" className="text-xs font-semibold text-navy-700" onClick={() => setConfirmReset(false)}>Cancel</button></span>}</div>
        : <button type="button" disabled={busy} data-testid="create-login" className={`${btn} bg-teal-700 text-white hover:bg-teal-800`} onClick={() => run(false)}>Create patient login</button>)}
      {cred && (
        <div className="rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm" data-testid="one-time-credentials">
          <p className="font-semibold text-navy-900">Patient Portal login created</p>
          <p className="mt-1">Username: <code className="rounded bg-white px-1.5 py-0.5">{cred.username}</code></p>
          <p className="mt-1">Password: <code className="rounded bg-white px-1.5 py-0.5" data-testid="one-time-password">{cred.password}</code>
            <button type="button" className="ml-2 text-xs font-semibold text-teal-700 hover:underline" onClick={() => void navigator.clipboard?.writeText(cred.password)}>Copy</button></p>
          <p className="mt-2 text-xs text-navy-700">Shown once: it is stored only as a hash. Give it to the patient securely.</p>
        </div>
      )}
      {err && <ErrorNote>{err}</ErrorNote>}
    </div>
  );
}

function AddPatient({ onCreated }: { onCreated: () => void }) {
  const empty = { name: "", birthDate: "", gender: "", dischargeDate: "", phone: "", email: "" };
  const [f, setF] = useState(empty);
  const [requestId, setRequestId] = useState(newId);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [dupOf, setDupOf] = useState<string | null>(null);
  const [created, setCreated] = useState<{ id: string; name: string } | null>(null);
  const today = new Date().toISOString().slice(0, 10);
  const fe = (k: string) => errors.find((e) => e.field === k)?.message;
  const set = (k: keyof typeof empty) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const submit = async (allowDuplicate = false) => {
    if (busy) return;
    setBusy(true); setErrors([]); setDupOf(null);
    try {
      const r = await createPatient({ name: f.name, birthDate: f.birthDate, gender: f.gender, dischargeDate: f.dischargeDate || undefined,
        phone: f.phone || undefined, email: f.email || undefined, requestId, allowDuplicate });
      setCreated({ id: r.id, name: r.name }); setF(empty); setRequestId(newId()); onCreated();
    } catch (e: any) {
      if (e instanceof FormError) { setErrors(e.errors); if (e.status === 409) setDupOf(e.duplicateOf ?? ""); }
      else setErrors([{ row: null, field: null, message: String(e?.message ?? e) }]);
    } finally { setBusy(false); }
  };
  if (created) {
    return (
      <div className="space-y-4" data-testid="patient-created">
        <p className="flex items-center gap-2 text-sm font-semibold text-teal-800"><IconCheck />{created.name} was registered as a FHIR Patient.</p>
        <div className="flex flex-wrap gap-3">
          <a href={`#/doctor/patients/${encodeURIComponent(created.id)}`} className={`${btn} bg-navy-900 text-white`}>Open patient</a>
          <button type="button" className={`${btn} border border-slate-300 bg-white text-navy-900`} onClick={() => setCreated(null)}>Add another patient</button>
        </div>
        <div className="border-t border-slate-100 pt-4"><p className="mb-2 text-sm font-medium text-navy-900">Patient Portal access (optional)</p><Credentials pid={created.id} /></div>
      </div>
    );
  }
  const general = errors.filter((e) => !["name", "birth_date", "gender", "discharge_date", "phone", "email"].includes(e.field ?? ""));
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void submit(false); }} noValidate data-testid="add-patient-form">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name *" error={fe("name") && dupOf === null ? fe("name") : undefined}><input className={input} value={f.name} onChange={set("name")} required autoComplete="off" data-testid="f-name" /></Field>
        <Field label="Date of birth *" error={fe("birth_date")}><input type="date" max={today} className={input} value={f.birthDate} onChange={set("birthDate")} required data-testid="f-dob" /></Field>
        <Field label="Gender *" hint="FHIR administrative gender" error={fe("gender")}>
          <select className={input} value={f.gender} onChange={set("gender")} required data-testid="f-gender">
            <option value="">Select…</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option><option value="unknown">Unknown</option>
          </select></Field>
        <Field label="Hospital discharge date" hint="Stored as the end of an inpatient Encounter" error={fe("discharge_date")}><input type="date" max={today} className={input} value={f.dischargeDate} onChange={set("dischargeDate")} data-testid="f-discharge" /></Field>
        <Field label="Phone" error={fe("phone")}><input type="tel" className={input} value={f.phone} onChange={set("phone")} autoComplete="off" /></Field>
        <Field label="Email" error={fe("email")}><input type="email" className={input} value={f.email} onChange={set("email")} autoComplete="off" /></Field>
      </div>
      {dupOf !== null && (
        <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900" role="alert" data-testid="duplicate-warning">
          {fe("name")}. {dupOf && <a className="font-semibold underline" href={`#/doctor/patients/${encodeURIComponent(dupOf)}`}>Open the existing record</a>}
          <button type="button" disabled={busy} className="ml-3 font-semibold underline" onClick={() => void submit(true)}>Register anyway</button>
        </div>
      )}
      {general.length > 0 && <ErrorNote>{general.map((e) => e.message).join(" ")}</ErrorNote>}
      <p className="text-xs text-navy-500">Conditions, medications and observations are not entered here: they are added only from real sources (FHIR records, monitoring or CSV import of measurements).</p>
      <button type="submit" disabled={busy} data-testid="f-submit" className={`${btn} bg-teal-700 text-white hover:bg-teal-800`}><IconPlus width={18} height={18} />{busy ? "Registering…" : "Register patient"}</button>
    </form>
  );
}

const TEMPLATES = {
  patients: { columns: "name,birth_date,gender,discharge_date", example: "Test Patient,1958-04-12,female,2026-11-01", required: ["name", "birth_date", "gender"] },
  observations: { columns: "patient_id,timestamp,heart_rate_bpm,spo2_percent,respiratory_rate_per_min,temperature_c", example: "<patient id>,2026-11-12T08:30:00Z,82,96,16,37.1", required: ["patient_id", "timestamp"] },
} as const;

/** One CSV template line: label, scrollable monospace text (never wider than the card) and a Copy button. */
function CsvLine({ label, text, testid }: { label: string; text: string; testid: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const t = document.createElement("textarea");
        t.value = text; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove();
      }
      setCopied(true); window.setTimeout(() => setCopied(false), 1500);
    } catch { setCopied(false); }
  };
  return (
    <div className="min-w-0">
      <p className="mb-1 font-medium text-navy-900">{label}</p>
      <div className="flex min-w-0 items-stretch gap-2">
        <code className="block min-w-0 max-w-full flex-1 overflow-x-auto whitespace-pre rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-[11px] text-navy-900" data-testid={testid}>{text}</code>
        <button type="button" onClick={() => void copy()} aria-label={`Copy ${label.toLowerCase()}`} data-testid={`${testid}-copy`}
          className="shrink-0 rounded-md border border-slate-300 bg-white px-2.5 text-[11px] font-semibold text-navy-900 hover:bg-slate-100">{copied ? "Copied" : "Copy"}</button>
      </div>
    </div>
  );
}

function ImportCsv({ onImported }: { onImported: () => void }) {
  const [kind, setKind] = useState<"patients" | "observations">("patients");
  const [file, setFile] = useState<{ name: string; header: string[]; rows: Record<string, string>[] } | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [check, setCheck] = useState<ImportResult | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState<"check" | "import" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const importId = useRef(newId());
  const inputRef = useRef<HTMLInputElement>(null);
  const reset = () => { setFile(null); setParseError(null); setCheck(null); setResult(null); setErr(null); setConfirming(false); importId.current = newId(); if (inputRef.current) inputRef.current.value = ""; };
  useEffect(reset, [kind]);
  const missing = file ? TEMPLATES[kind].required.filter((c) => !file.header.includes(c)) : [];
  const onFile = async (fl: File | undefined) => {
    reset();
    if (!fl) return;
    if (fl.size > 1_000_000) { setParseError("The file is larger than 1 MB."); return; }
    const parsed = parseCsv(await fl.text());
    if (parsed.error) { setParseError(parsed.error); return; }
    setFile({ name: fl.name, header: parsed.header, rows: parsed.rows });
  };
  const validate = async () => {
    if (!file) return;
    setBusy("check"); setErr(null);
    try { setCheck(await importCsv(kind, file.rows, false, file.name, importId.current)); } catch (e: any) { setErr(String(e?.message ?? e)); } finally { setBusy(null); }
  };
  const doImport = async () => {
    if (!file) return;
    setBusy("import"); setErr(null); setConfirming(false);
    try { const r = await importCsv(kind, file.rows, true, file.name, importId.current); setResult(r); if (r.imported) onImported(); }
    catch (e: any) { setErr(String(e?.message ?? e)); } finally { setBusy(null); }
  };
  return (
    <div className="space-y-4">
      <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2" role="radiogroup" aria-label="CSV type">
        {(["patients", "observations"] as const).map((k) => (
          <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)} data-testid={`import-kind-${k}`}
            className={`min-w-0 rounded-lg px-4 py-2 text-center text-sm font-semibold ${kind === k ? "bg-navy-900 text-white" : "border border-slate-300 bg-white text-navy-900"}`}>
            {k === "patients" ? "Patient records" : "Vital-sign observations"}</button>
        ))}
      </div>
      <div className="min-w-0 space-y-2 rounded-lg bg-slate-50 p-3 text-xs text-navy-700">
        <CsvLine label="Columns" text={TEMPLATES[kind].columns} testid="csv-columns" />
        <CsvLine label="Example" text={TEMPLATES[kind].example} testid="csv-example" />
        <p className="break-words">{kind === "patients" ? "Dates as YYYY-MM-DD; gender male, female, other or unknown; discharge_date optional. Up to 200 rows."
          : "Timestamps in ISO 8601 with a timezone. Units: bpm, %, breaths/min, °C. Leave a value empty if not measured. Stored as FHIR Observations labelled \"CSV import\" (not wearable readings). Up to 100 rows."}</p>
      </div>
      <input ref={inputRef} type="file" accept=".csv,text/csv" onChange={(e) => void onFile(e.target.files?.[0])} data-testid="csv-file"
        className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-teal-700 file:px-4 file:py-2 file:font-semibold file:text-white" aria-label="Choose a CSV file" />
      {parseError && <ErrorNote>{parseError}</ErrorNote>}
      {file && (
        <div className="space-y-3">
          <p className="text-sm text-navy-700"><strong>{file.name}</strong>: {file.rows.length} data row{file.rows.length === 1 ? "" : "s"}. Preview of the first {Math.min(5, file.rows.length)}:</p>
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-left text-xs" data-testid="csv-preview">
              <thead className="bg-slate-50"><tr><th className="px-2 py-1.5">Row</th>{file.header.map((h) => <th key={h} className="px-2 py-1.5 font-semibold">{h}</th>)}</tr></thead>
              <tbody>{file.rows.slice(0, 5).map((r, i) => <tr key={i} className="border-t border-slate-100"><td className="px-2 py-1 text-navy-500">{i + 2}</td>{file.header.map((h) => <td key={h} className="px-2 py-1">{r[h]}</td>)}</tr>)}</tbody>
            </table>
          </div>
          {missing.length > 0 && <ErrorNote>Missing required column(s): {missing.join(", ")}.</ErrorNote>}
          {!check && <button type="button" disabled={busy !== null || missing.length > 0 || !file.rows.length} onClick={validate} data-testid="csv-validate"
            className={`${btn} bg-navy-900 text-white`}>{busy === "check" ? "Validating…" : "Validate file"}</button>}
          {check && !check.valid && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900" data-testid="csv-errors" role="alert">
              <p className="font-semibold">{check.message ?? "The file has errors. Nothing was imported."} ({check.errors.length} problem{check.errors.length === 1 ? "" : "s"})</p>
              <ul className="mt-2 max-h-56 list-disc space-y-0.5 overflow-y-auto pl-5">{check.errors.slice(0, 50).map((e, i) => <li key={i}>{e.row ? `Row ${e.row}` : "File"}{e.field ? `, ${e.field}` : ""}: {e.message}</li>)}</ul>
              <button type="button" className="mt-2 font-semibold underline" onClick={reset}>Choose another file</button>
            </div>
          )}
          {check?.valid && !result && (
            <div className="rounded-lg border border-teal-200 bg-teal-50 p-3 text-sm" data-testid="csv-ready">
              <p className="font-semibold text-navy-900">All rows are valid: {check.ready} {kind === "patients" ? "patient record" : "observation"}{check.ready === 1 ? "" : "s"} ready to import.</p>
              {!confirming ? (
                <button type="button" disabled={busy !== null} onClick={() => setConfirming(true)} data-testid="csv-import" className={`${btn} mt-3 bg-teal-700 text-white`}><IconUpload width={18} height={18} />Import…</button>
              ) : (
                <div className="mt-3 rounded-lg bg-white p-3 ring-1 ring-slate-200" role="alertdialog" aria-label="Confirm import">
                  <p>Write {check.ready} {kind === "patients" ? "Patient resource(s)" : "Observation resource(s)"} to the FHIR server? This cannot be undone from the portal.</p>
                  <div className="mt-2 flex gap-2">
                    <button type="button" disabled={busy !== null} onClick={doImport} data-testid="csv-confirm" className={`${btn} bg-teal-700 text-white`}>{busy === "import" ? "Importing…" : "Confirm import"}</button>
                    <button type="button" onClick={() => setConfirming(false)} className={`${btn} border border-slate-300 bg-white text-navy-900`}>Cancel</button>
                  </div>
                </div>
              )}
            </div>
          )}
          {result && (
            <div className={`rounded-lg border p-3 text-sm ${result.rejected ? "border-amber-300 bg-amber-50" : "border-teal-200 bg-teal-50"}`} data-testid="csv-result">
              <p className="font-semibold">Import finished: {result.imported} stored, {result.rejected} rejected.</p>
              {(result.results ?? []).filter((r) => !r.ok).slice(0, 20).map((r, i) => <p key={i} className="text-xs">Row {r.row}: {r.error}</p>)}
              <button type="button" className="mt-2 font-semibold underline" onClick={reset}>Import another file</button>
            </div>
          )}
          {err && <ErrorNote>{err}</ErrorNote>}
        </div>
      )}
    </div>
  );
}

function Exports() {
  const { data } = useOverview(30000);
  const pts = useMemo(() => [...(data?.patients ?? [])].sort((a, b) => displayName(a.name).localeCompare(displayName(b.name))), [data]);
  const [pid, setPid] = useState("");
  const link = `${btn} border border-slate-300 bg-white text-navy-900 hover:bg-slate-50`;
  return (
    <div className="space-y-5">
      <div><p className="text-sm font-medium text-navy-900">Patient directory</p>
        <a href={exportUrls.directory} download className={`${link} mt-2`} data-testid="export-directory"><IconDownload width={18} height={18} />Download patients.csv</a></div>
      <div className="border-t border-slate-100 pt-4">
        <label className="text-sm font-medium text-navy-900">Individual patient
          <select value={pid} onChange={(e) => setPid(e.target.value)} className={`${input} mt-1 max-w-sm`} data-testid="export-patient">
            <option value="">Select a patient…</option>{pts.map((p) => <option key={p.id} value={p.id}>{displayName(p.name)}</option>)}
          </select></label>
        {pid && <div className="mt-3 flex flex-wrap gap-2">
          <a href={exportUrls.record(pid)} download className={link}><IconDownload width={18} height={18} />Medical record CSV</a>
          <a href={exportUrls.observations(pid)} download className={link}><IconDownload width={18} height={18} />Vital-sign history CSV</a>
        </div>}
      </div>
      <p className="text-xs text-navy-500">UTF-8 CSV with one header row; values that could be read as spreadsheet formulas are prefixed with an apostrophe. Exports contain synthetic test data only.</p>
    </div>
  );
}

function Logins() {
  const { data } = useOverview(30000);
  const pts = useMemo(() => [...(data?.patients ?? [])].sort((a, b) => displayName(a.name).localeCompare(displayName(b.name))), [data]);
  const [pid, setPid] = useState("");
  return (
    <div className="space-y-3">
      <select value={pid} onChange={(e) => setPid(e.target.value)} className={`${input} max-w-sm`} aria-label="Patient" data-testid="login-patient">
        <option value="">Select a patient…</option>{pts.map((p) => <option key={p.id} value={p.id}>{displayName(p.name)}</option>)}
      </select>
      {pid && <Credentials pid={pid} />}
    </div>
  );
}

export function DataManagement() {
  const [tick, setTick] = useState(0);
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card title="Add patient" className="xl:row-span-2"><AddPatient onCreated={() => setTick(tick + 1)} /></Card>
      <Card title="Import CSV"><ImportCsv onImported={() => setTick(tick + 1)} /></Card>
      <Card title="Export CSV"><Exports /></Card>
      <Card title="Patient Portal logins" className="xl:col-span-2">
        <p className="mb-3 text-sm text-navy-700">Create a login for a patient explicitly. A random password is generated and shown once; there are no default passwords.</p>
        <Logins />
      </Card>
    </div>
  );
}

export function VideoLink({ label, testid, className = "" }: { label: string; testid: string; className?: string }) {
  return (
    <a href={SPARKMEET_URL} target="_blank" rel="noopener noreferrer" data-testid={testid}
      className={`inline-flex items-center gap-2 rounded-lg bg-teal-700 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-teal-800 ${className}`}>
      <IconVideo width={18} height={18} />{label}<IconExternal width={16} height={16} aria-label="opens an external site in a new tab" />
    </a>
  );
}

export function VideoConsultation({ role }: { role: "doctor" | "patient" }) {
  return (
    <Card>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-teal-50 text-teal-700"><IconVideo width={28} height={28} /></span>
        <div className="space-y-3">
          <h2 className="text-xl font-semibold text-navy-900">Video consultation</h2>
          <p className="max-w-2xl text-sm text-navy-700">Video calls use <strong>SparkMeet</strong>, an external service that opens in a new browser tab.
            {role === "doctor" ? " Agree the meeting details with the patient within SparkMeet." : " Join using the meeting details your care team gives you."}</p>
          <VideoLink label={role === "doctor" ? "Start Video Consultation" : "Join Video Consultation"} testid={`video-${role}`} />
          <p className="flex items-center gap-1.5 text-xs text-navy-500"><IconExternal width={14} height={14} />External service: {new URL(SPARKMEET_URL).host}. No patient details are sent to it by Arogya Drishti; rooms and invitations are managed in SparkMeet.</p>
        </div>
      </div>
    </Card>
  );
}
