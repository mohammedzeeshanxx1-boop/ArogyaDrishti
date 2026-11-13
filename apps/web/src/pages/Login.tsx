import { useState } from "react";
import { login, type User } from "../api";
import { BRAND } from "../brand";
import { IconEye, IconShield } from "../components/icons";

export function Login({ onSignedIn, notice }: { onSignedIn: (u: User) => void; notice?: string | null }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try { onSignedIn((await login(username.trim(), password)).user); }
    catch (err: any) { setError(err?.status === 0 || err instanceof TypeError ? "Cannot reach the server." : String(err?.message ?? err)); }
    finally { setBusy(false); }
  };
  return (
    <div className="grid min-h-screen bg-surface font-sans text-navy-900 lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-navy-900 p-12 text-white lg:flex">
        <div className="flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-teal-600"><IconEye width={24} height={24} /></span>
          <span><span className="block text-lg font-bold tracking-wide">AROGYA DRISHTI</span><span className="block text-sm text-slate-300">Personalized Post-Discharge Patient Monitoring</span></span>
        </div>
        <div>
          <p className="max-w-md text-3xl font-semibold leading-snug">{BRAND.tagline}</p>
          <p className="mt-4 max-w-md text-sm text-slate-300">Doctors monitor discharged patients' vital signs against personal baselines. Patients see their own readings and records.</p>
        </div>
        <p className="text-xs text-slate-400">{BRAND.disclaimer} Prototype with synthetic patient records and simulated vital signs.</p>
      </div>
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-2xl border border-slate-200 bg-white p-8 shadow-sm" aria-labelledby="signin-title">
          <div>
            <h1 id="signin-title" className="text-2xl font-semibold">Sign in</h1>
            <p className="mt-1 text-sm text-navy-500">Doctor Portal and Patient Portal</p>
          </div>
          {notice && <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">{notice}</p>}
          <label className="block text-sm font-medium text-navy-700">Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required data-testid="username"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm" />
          </label>
          <label className="block text-sm font-medium text-navy-700">Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required data-testid="password"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm" />
          </label>
          {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800" data-testid="login-error">{error}</p>}
          <button type="submit" disabled={busy} data-testid="sign-in"
            className="w-full rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-teal-800 disabled:opacity-50">{busy ? "Signing in…" : "Sign in"}</button>
          <p className="flex items-start gap-2 text-xs text-navy-500"><IconShield className="mt-0.5 shrink-0" width={16} height={16} />
            Welcome back. Sign in securely to continue.</p>
        </form>
      </div>
    </div>
  );
}
