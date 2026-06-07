import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchRun, type RunDetail as RunDetailT } from "./api";
import { StageCard } from "./StageCard";

export function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunDetailT | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    fetchRun(id).then(setRun).catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <p style={{ color: "crimson" }}>Failed to load run: {error}</p>;
  if (run === null) return <p>Loading…</p>;

  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>
        <span style={{ fontFamily: "monospace" }}>{run.run_id}</span>{" "}
        <span style={{ background: "#eef", borderRadius: 4, padding: "2px 8px", fontSize: 14 }}>
          {run.command_type}
        </span>{" "}
        {run.decision && <span>· {run.decision}</span>}
      </h2>
      <p style={{ color: "#444" }}>{run.task}</p>
      <div style={{ marginTop: 16 }}>
        {run.stages.map((s, i) => <StageCard key={i} stage={s} />)}
      </div>
    </div>
  );
}
