import { useCallback, useEffect, useState } from "react";
import { fetchMe, fetchStatus, logout, setUnauthorizedHandler, type StatusResponse, type User } from "./api";
import { IconBell, IconChart, IconDatabase, IconFile, IconFlask, IconGrid, IconPulse, IconShield, IconUser, IconUsers, IconVideo } from "./components/icons";
import { EarlyDetectionLab } from "./pages/lab";
import { SensorReliabilityLab } from "./pages/sensorlab";
import { NotificationBell, NotificationProvider } from "./notifications";
import { DataManagement, VideoConsultation } from "./pages/data";
import { Shell, type NavItem } from "./components/Shell";
import { displayName } from "./components/ui";
import { useMonitor } from "./monitor";
import { AlertsPage, DoctorDashboard, PatientDirectory, PatientMonitor } from "./pages/doctor";
import { Login } from "./pages/Login";
import { MyHealth, MyProfile, MyRecords, MyTrends } from "./pages/patient";

const DOCTOR_NAV: NavItem[] = [
  { href: "#/doctor", label: "Dashboard", icon: IconGrid, match: (h) => h === "#/doctor" || h === "#/doctor/" },
  { href: "#/doctor/patients", label: "Patients", icon: IconUsers, match: (h) => h.startsWith("#/doctor/patients") },
  { href: "#/doctor/alerts", label: "Alerts", icon: IconBell, match: (h) => h.startsWith("#/doctor/alerts") },
  { href: "#/doctor/lab", label: "Early Detection Lab", icon: IconFlask, match: (h) => h.startsWith("#/doctor/lab") },
  { href: "#/doctor/sensor-lab", label: "Sensor Reliability Lab", icon: IconShield, match: (h) => h.startsWith("#/doctor/sensor-lab") },
  { href: "#/doctor/data", label: "Data Management", icon: IconDatabase, match: (h) => h.startsWith("#/doctor/data") },
  { href: "#/doctor/video", label: "Video Consultation", icon: IconVideo, match: (h) => h.startsWith("#/doctor/video") },
];
const PATIENT_NAV: NavItem[] = [
  { href: "#/me", label: "My Health", icon: IconPulse, match: (h) => h === "#/me" || h === "#/me/" },
  { href: "#/me/trends", label: "My Health Trends", icon: IconChart, match: (h) => h.startsWith("#/me/trends") },
  { href: "#/me/records", label: "My Medical Records", icon: IconFile, match: (h) => h.startsWith("#/me/records") },
  { href: "#/me/profile", label: "My Profile", icon: IconUser, match: (h) => h.startsWith("#/me/profile") },
  { href: "#/me/video", label: "Video Consultation", icon: IconVideo, match: (h) => h.startsWith("#/me/video") },
];

function useHash() {
  const [hash, setHash] = useState(() => window.location.hash || "#/");
  useEffect(() => {
    const on = () => { setHash(window.location.hash || "#/"); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function useServiceStatus() {
  const [status, setStatus] = useState<StatusResponse | "down" | null>(null);
  useEffect(() => {
    const load = () => fetchStatus().then(setStatus).catch(() => setStatus("down"));
    load();
    const t = window.setInterval(load, 10000);
    return () => window.clearInterval(t);
  }, []);
  return status;
}

function DoctorPortal({ user, hash, status, onSignOut }: { user: User; hash: string; status: StatusResponse | "down" | null; onSignOut: () => void }) {
  const m = hash.match(/^#\/doctor\/patients\/([^/?#]+)/);
  const pid = m ? decodeURIComponent(m[1]) : null;
  const [title, page] = pid ? ["Patient monitoring", <PatientMonitor key={pid} pid={pid} />]
    : hash.startsWith("#/doctor/patients") ? ["Patient directory", <PatientDirectory />]
      : hash.startsWith("#/doctor/alerts") ? ["Alerts", <AlertsPage />]
        : hash.startsWith("#/doctor/lab") ? ["Early Detection Lab", <EarlyDetectionLab />]
        : hash.startsWith("#/doctor/sensor-lab") ? ["Sensor Reliability Lab", <SensorReliabilityLab />]
        : hash.startsWith("#/doctor/data") ? ["Data Management", <DataManagement />]
          : hash.startsWith("#/doctor/video") ? ["Video Consultation", <VideoConsultation role="doctor" />]
            : ["Dashboard", <DoctorDashboard />];
  // The notification listener and toasts live in the portal shell, so they persist across page navigation.
  return (
    <NotificationProvider>
      <Shell portal="Doctor Portal" user={user} nav={DOCTOR_NAV} hash={hash} title={title as string} status={status} onSignOut={onSignOut}
        subtitle="Personalized post-discharge patient monitoring" headerRight={<NotificationBell />}>{page}</Shell>
    </NotificationProvider>
  );
}

function PatientPortal({ user, hash, status, onSignOut }: { user: User; hash: string; status: StatusResponse | "down" | null; onSignOut: () => void }) {
  const pid = user.patientId!;
  const { monitor, live } = useMonitor(pid);   // one live connection shared by all patient pages
  const [title, page] = hash.startsWith("#/me/trends") ? ["My Health Trends", <MyTrends monitor={monitor} />]
    : hash.startsWith("#/me/records") ? ["My Medical Records", <MyRecords pid={pid} />]
      : hash.startsWith("#/me/profile") ? ["My Profile", <MyProfile user={user} pid={pid} monitor={monitor} />]
        : hash.startsWith("#/me/video") ? ["Video Consultation", <VideoConsultation role="patient" />]
        : ["My Health", <MyHealth user={user} monitor={monitor} live={live} />];
  return (
    <Shell portal="Patient Portal" user={{ ...user, displayName: displayName(user.displayName) }} nav={PATIENT_NAV} hash={hash} title={title as string}
      status={status} onSignOut={onSignOut} subtitle="Your home monitoring readings and health record">{page}</Shell>
  );
}

export default function App() {
  const hash = useHash();
  const status = useServiceStatus();
  const [user, setUser] = useState<User | null | undefined>(undefined);   // undefined = checking session
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    fetchMe().then((r) => setUser(r.user)).catch(() => setUser(null));
    setUnauthorizedHandler(() => { setUser(null); setNotice("Your session has ended. Please sign in again."); });
    return () => setUnauthorizedHandler(null);
  }, []);

  // Role-aware routing: each role lands on its own portal and cannot open the other one.
  useEffect(() => {
    if (!user) return;
    const home = user.role === "doctor" ? "#/doctor" : "#/me";
    const legacy = hash.match(/^#\/patient\/([^/?#]+)/);
    if (user.role === "doctor" && legacy) window.location.hash = `#/doctor/patients/${legacy[1]}`;
    else if (user.role === "doctor" && !hash.startsWith("#/doctor")) window.location.hash = home;
    else if (user.role === "patient" && !hash.startsWith("#/me")) window.location.hash = home;
  }, [user, hash]);

  const signOut = useCallback(async () => {
    try { await logout(); } catch { /* the session is cleared locally either way */ }
    setUser(null); setNotice(null); window.location.hash = "#/";
  }, []);

  if (user === undefined) {
    return <div className="grid min-h-screen place-items-center bg-surface text-sm text-navy-500" role="status">Loading…</div>;
  }
  if (user === null) {
    return <Login notice={notice ?? (status === "down" ? "The server is not reachable right now. Please try again shortly." : null)}
      onSignedIn={(u) => { setNotice(null); setUser(u); window.location.hash = u.role === "doctor" ? "#/doctor" : "#/me"; }} />;
  }
  return user.role === "doctor"
    ? <DoctorPortal user={user} hash={hash} status={status} onSignOut={signOut} />
    : <PatientPortal user={user} hash={hash} status={status} onSignOut={signOut} />;
}
