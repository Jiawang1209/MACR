import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LiveRun } from "./LiveRun";

// Minimal mock WebSocket capturing sends and exposing a way to push server events.
class MockWS {
  static last: MockWS | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];
  constructor(_url: string) { MockWS.last = this; }
  send(data: string) { this.sent.push(data); }
  close() {}
  push(obj: unknown) { this.onmessage?.({ data: JSON.stringify(obj) }); }
}

test("renders streamed stages, shows gate panel, sends response", async () => {
  (globalThis as any).WebSocket = MockWS as unknown as typeof WebSocket;
  render(<MemoryRouter><LiveRun /></MemoryRouter>);
  const ws = MockWS.last!;

  act(() => ws.push({ type: "stage", stage: { kind: "plan", label: "Planner", agent: "claude", status: null, body: {} } }));
  await waitFor(() => expect(screen.getByText("Planner")).toBeInTheDocument());

  act(() => ws.push({ type: "gate_request", gate: "final", data: { tests: { passed: true } } }));
  await waitFor(() => expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument());

  fireEvent.click(screen.getByRole("button", { name: /approve/i }));
  expect(JSON.parse(ws.sent[0])).toMatchObject({ decision: "approve" });

  act(() => ws.push({ type: "done", run_id: "R1", decision: "approve" }));
  await waitFor(() => expect(screen.getByText(/R1/)).toBeInTheDocument());
});
