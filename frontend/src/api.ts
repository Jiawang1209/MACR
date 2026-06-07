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
