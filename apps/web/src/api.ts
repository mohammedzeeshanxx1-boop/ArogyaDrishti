export type ServiceState = "ok" | "unreachable" | "error" | "checking";

export interface StatusResponse {
  checkedAt: string;
  checkpoint: string;
  services: {
    api: { status: ServiceState; version?: string };
    fhir: { status: ServiceState; url?: string; fhirVersion?: string; isR4?: boolean; software?: string; detail?: string };
    eventStore: { status: ServiceState; schemaVersion?: number; detail?: string };
  };
}

export async function fetchStatus(signal?: AbortSignal): Promise<StatusResponse> {
  const resp = await fetch("/api/v1/status", { signal });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as StatusResponse;
}

/** Opens the heartbeat socket once and resolves true if the server says hello. */
export function probeWebSocket(timeoutMs = 4000): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (ok: boolean, ws?: WebSocket) => {
      if (settled) return;
      settled = true;
      ws?.close();
      resolve(ok);
    };
    try {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${scheme}://${window.location.host}/ws/heartbeat`);
      const timer = window.setTimeout(() => finish(false, ws), timeoutMs);
      ws.onmessage = (event) => {
        window.clearTimeout(timer);
        try {
          finish(JSON.parse(String(event.data)).type === "hello", ws);
        } catch {
          finish(false, ws);
        }
      };
      ws.onerror = () => {
        window.clearTimeout(timer);
        finish(false, ws);
      };
    } catch {
      finish(false);
    }
  });
}
