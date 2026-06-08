import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LaunchForm } from "./LaunchForm";

test("submits a launch request with the entered fields", async () => {
  const calls: any[] = [];
  globalThis.fetch = ((url: string, init: any) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ run_id: "R1", command: "collab" }) });
  }) as unknown as typeof fetch;

  render(<MemoryRouter><LaunchForm /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText(/task/i), { target: { value: "add a function" } });
  fireEvent.change(screen.getByLabelText(/repo/i), { target: { value: "/tmp/r" } });
  fireEvent.change(screen.getByLabelText(/test command/i), { target: { value: "pytest -q" } });
  fireEvent.click(screen.getByRole("button", { name: /launch/i }));

  await waitFor(() => expect(calls.length).toBe(1));
  expect(calls[0].url).toBe("/api/runs/launch");
  expect(calls[0].body).toMatchObject({ command: "collab", task: "add a function",
    repo: "/tmp/r", test_cmd: "pytest -q" });
});
