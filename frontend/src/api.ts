export interface Stage {
  kind: string;
  label: string;
  agent: string | null;
  status: string | null;
  body: Record<string, unknown>;
}
export interface Artifact { name: string; kind: string; }
export interface RunSummary {
  run_id: string;
  command_type: string;
  task: string;
  decision: string | null;
  broken: boolean;
}
export interface RunDetail {
  run_id: string;
  command_type: string;
  task: string;
  repo: string | null;
  worktree: string | null;
  decision: string | null;
  stages: Stage[];
  artifacts: Artifact[];
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const fetchRuns = () => getJSON<RunSummary[]>("/api/runs");
export const fetchRun = (id: string) => getJSON<RunDetail>(`/api/runs/${id}`);

export interface LiveEvent {
  type: "stage" | "note" | "gate_request" | "status" | "done" | "error";
  stage?: Stage;
  text?: string;
  gate?: "consensus" | "final";
  data?: Record<string, unknown>;
  status?: string;
  run_id?: string;
  decision?: string | null;
  message?: string;
}

export interface LaunchBody {
  command: "collab" | "discuss";
  task: string;
  repo: string;
  test_cmd: string;
  options?: Record<string, unknown>;
}

export async function launchRun(body: LaunchBody): Promise<{ run_id: string; command: string }> {
  const res = await fetch("/api/runs/launch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
  return res.json();
}

export function activeWsUrl(): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/api/runs/active/ws`;
}
