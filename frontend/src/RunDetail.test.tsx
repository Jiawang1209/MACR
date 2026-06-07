import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { RunDetail } from "./RunDetail";
import type { RunDetail as RunDetailT } from "./api";

function mockFetch(data: RunDetailT) {
  globalThis.fetch = (() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(data) })) as unknown as typeof fetch;
}

const detail: RunDetailT = {
  run_id: "R1", command_type: "collab", task: "add add()", repo: "/tmp/r",
  worktree: "/tmp/wt", decision: "approve",
  stages: [
    { kind: "plan", label: "Planner", agent: "claude", status: null, body: { summary: "plan it", steps: ["read"] } },
    { kind: "executor", label: "Executor #1", agent: "codex", status: null, body: { artifact: "def add", notes: "" } },
    { kind: "tests", label: "Tests #1", agent: null, status: "passed", body: { command: "t", exit_code: 0, log: "OK" } },
    { kind: "gate", label: "Human Gate", agent: null, status: "approve", body: { feedback: "" } },
  ],
  artifacts: [{ name: "diff.v1.patch", kind: "diff" }],
};

test("renders each stage label and the task", async () => {
  mockFetch(detail);
  render(
    <MemoryRouter initialEntries={["/runs/R1"]}>
      <Routes><Route path="/runs/:id" element={<RunDetail />} /></Routes>
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText("add add()")).toBeInTheDocument());
  expect(screen.getByText("Planner")).toBeInTheDocument();
  expect(screen.getByText("Executor #1")).toBeInTheDocument();
  expect(screen.getByText("Tests #1")).toBeInTheDocument();
  expect(screen.getByText("Human Gate")).toBeInTheDocument();
  expect(screen.getByText("passed")).toBeInTheDocument();
});
