import type { Stage } from "./api";

function Body({ stage }: { stage: Stage }) {
  const b = stage.body as Record<string, unknown>;
  if (stage.kind === "plan" || stage.kind === "consensus") {
    return (
      <div>
        <p>{String(b.summary ?? "")}</p>
        <ol>{(b.steps as string[] | undefined)?.map((s, i) => <li key={i}>{s}</li>)}</ol>
      </div>
    );
  }
  if (stage.kind === "executor") return <pre>{String(b.artifact ?? "")}</pre>;
  if (stage.kind === "tests") return <pre>{String(b.log ?? "")}</pre>;
  if (stage.kind === "reviewer" || stage.kind === "plan_review") return <p>{String(b.summary ?? "")}</p>;
  if (stage.kind === "turn") return <p>{String(b.response ?? b.text ?? "")}</p>;
  if (stage.kind === "gate") return <p>{String(b.feedback ?? "")}</p>;
  return null;
}

export function StageCard({ stage }: { stage: Stage }) {
  return (
    <div style={{ borderLeft: "3px solid #88a", margin: "0 0 12px 8px", padding: "4px 0 4px 16px" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
        <strong>{stage.label}</strong>
        {stage.agent && <span style={{ color: "#666", fontSize: 12 }}>{stage.agent}</span>}
        {stage.status && (
          <span style={{ marginLeft: "auto", background: "#efe", borderRadius: 4, padding: "1px 8px" }}>
            {stage.status}
          </span>
        )}
      </div>
      <Body stage={stage} />
    </div>
  );
}
