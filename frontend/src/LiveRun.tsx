import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { activeWsUrl, type LiveEvent, type Stage } from "./api";
import { StageCard } from "./StageCard";
import { GatePanel } from "./GatePanel";

export function LiveRun() {
  const [stages, setStages] = useState<Stage[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [gate, setGate] = useState<"consensus" | "final" | null>(null);
  const [done, setDone] = useState<{ run_id: string; decision: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(activeWsUrl());
    wsRef.current = ws;
    ws.onmessage = (e) => {
      const ev: LiveEvent = JSON.parse(e.data);
      if (ev.type === "stage" && ev.stage) setStages((s) => [...s, ev.stage!]);
      else if (ev.type === "note" && ev.text) setNotes((n) => [...n, ev.text!]);
      else if (ev.type === "gate_request") setGate(ev.gate ?? "final");
      else if (ev.type === "status" && ev.status === "running") setGate(null);
      else if (ev.type === "done") setDone({ run_id: ev.run_id!, decision: ev.decision ?? null });
      else if (ev.type === "error") setError(ev.message ?? "error");
    };
    return () => ws.close();
  }, []);

  function respond(decision: "approve" | "reject", feedback: string) {
    wsRef.current?.send(JSON.stringify({ decision, feedback }));
    setGate(null);
  }

  return (
    <div>
      <h2>Live run</h2>
      {error && <p style={{ color: "crimson" }}>Error: {error}</p>}
      {gate && <GatePanel gate={gate} onRespond={respond} />}
      {done && (
        <p>Done — decision: <strong>{done.decision}</strong>{" · "}
          <Link to={`/runs/${done.run_id}`}>{done.run_id} — view saved run</Link></p>
      )}
      <div>{stages.map((s, i) => <StageCard key={i} stage={s} />)}</div>
      {notes.length > 0 && (
        <pre style={{ background: "#f6f6f6", padding: 8, fontSize: 12 }}>{notes.join("\n")}</pre>
      )}
    </div>
  );
}
