import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

class FakeSocket {
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    setTimeout(() => this.onmessage?.({ data: JSON.stringify({ type: "hello" }) }), 0);
  }
  close() {}
}

afterEach(() => vi.unstubAllGlobals());

describe("App (C0 shell)", () => {
  it("always shows brand, tagline and disclaimer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    vi.stubGlobal("WebSocket", FakeSocket);
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Arogya Drishti" })).toBeInTheDocument();
    expect(screen.getByText("See the warning signs before they become emergencies.")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Clinical decision support only. Not for medical diagnosis.");
    await waitFor(() => expect(screen.getByTestId("state-Live channel")).toHaveTextContent("Connected"));
  });

  it("does not show services as connected when the API is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    vi.stubGlobal("WebSocket", FakeSocket);
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("state-API")).toHaveTextContent("Unreachable"));
    expect(screen.getByTestId("state-HAPI FHIR")).toHaveTextContent("Unreachable");
    expect(screen.getByTestId("state-Event store")).toHaveTextContent("Unreachable");
  });

  it("reports HAPI state from the API response", async () => {
    const body = {
      checkedAt: "2026-01-01T00:00:00+00:00",
      checkpoint: "C0",
      services: {
        api: { status: "ok", version: "0.0.1" },
        fhir: { status: "unreachable", detail: "ConnectError" },
        eventStore: { status: "ok", schemaVersion: 1 },
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => body }));
    vi.stubGlobal("WebSocket", FakeSocket);
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("state-API")).toHaveTextContent("Connected"));
    expect(screen.getByTestId("state-HAPI FHIR")).toHaveTextContent("Unreachable");
    expect(screen.getByTestId("state-Event store")).toHaveTextContent("Connected");
  });
});
