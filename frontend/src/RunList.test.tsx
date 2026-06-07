import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RunList } from "./RunList";
import type { RunSummary } from "./api";

function mockFetch(data: RunSummary[]) {
  globalThis.fetch = (() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(data) })) as unknown as typeof fetch;
}

test("renders run rows with type badge and decision", async () => {
  mockFetch([
    { run_id: "R20260607_002", command_type: "discuss", task: "build add()", decision: "approve", broken: false },
    { run_id: "R20260607_001", command_type: "collab", task: "do it", decision: null, broken: false },
  ]);
  render(<MemoryRouter><RunList /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("R20260607_002")).toBeInTheDocument());
  expect(screen.getByText("discuss")).toBeInTheDocument();
  expect(screen.getByText("build add()")).toBeInTheDocument();
  expect(screen.getByText("approve")).toBeInTheDocument();
});

test("shows empty state when there are no runs", async () => {
  mockFetch([]);
  render(<MemoryRouter><RunList /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText(/no runs/i)).toBeInTheDocument());
});
