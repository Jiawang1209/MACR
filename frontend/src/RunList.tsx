import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchRuns, type RunSummary } from "./api";

export function RunList() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRuns().then(setRuns).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p style={{ color: "crimson" }}>Failed to load runs: {error}</p>;
  if (runs === null) return <p>Loading…</p>;
  if (runs.length === 0) return <p>No runs yet.</p>;

  return (
    <table style={{ borderCollapse: "collapse", width: "100%" }}>
      <tbody>
        {runs.map((r) => (
          <tr key={r.run_id} style={{ borderBottom: "1px solid #eee", opacity: r.broken ? 0.5 : 1 }}>
            <td style={{ padding: "8px 12px", fontFamily: "monospace" }}>
              <Link to={`/runs/${r.run_id}`}>{r.run_id}</Link>
            </td>
            <td style={{ padding: "8px 12px" }}>
              <span style={{ background: "#eef", borderRadius: 4, padding: "2px 8px" }}>
                {r.command_type}
              </span>
            </td>
            <td style={{ padding: "8px 12px" }}>{r.task}</td>
            <td style={{ padding: "8px 12px" }}>{r.broken ? "(broken)" : r.decision ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
