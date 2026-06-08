import { useState } from "react";

export function GatePanel({ gate, onRespond }: {
  gate: "consensus" | "final";
  onRespond: (decision: "approve" | "reject", feedback: string) => void;
}) {
  const [feedback, setFeedback] = useState("");
  return (
    <div style={{ border: "2px solid #88a", borderRadius: 6, padding: 12, margin: "12px 0" }}>
      <strong>Human gate: {gate}</strong>
      <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)}
                placeholder="optional feedback / annotation" rows={2} style={{ display: "block", width: "100%", margin: "8px 0" }} />
      <button onClick={() => onRespond("approve", feedback)}>Approve</button>{" "}
      <button onClick={() => onRespond("reject", feedback)}>Reject</button>
    </div>
  );
}
