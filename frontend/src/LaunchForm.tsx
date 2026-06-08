import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { launchRun } from "./api";

export function LaunchForm() {
  const nav = useNavigate();
  const [command, setCommand] = useState<"collab" | "discuss">("collab");
  const [task, setTask] = useState("");
  const [repo, setRepo] = useState("");
  const [testCmd, setTestCmd] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await launchRun({ command, task, repo, test_cmd: testCmd });
      nav("/live");
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: 12, maxWidth: 560 }}>
      <label> Command
        <select value={command} onChange={(e) => setCommand(e.target.value as "collab" | "discuss")}>
          <option value="collab">collab</option>
          <option value="discuss">discuss</option>
        </select>
      </label>
      <label> Task
        <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={3} />
      </label>
      <label> Repo
        <input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="/path/to/repo" />
      </label>
      <label> Test command
        <input value={testCmd} onChange={(e) => setTestCmd(e.target.value)} placeholder="pytest -q" />
      </label>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      <button type="submit">Launch</button>
    </form>
  );
}
