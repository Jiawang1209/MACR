import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { RunList } from "./RunList";
import { RunDetail } from "./RunDetail";
import { LaunchForm } from "./LaunchForm";
import { LiveRun } from "./LiveRun";

export function App() {
  return (
    <BrowserRouter>
      <header style={{ padding: "12px 16px", borderBottom: "1px solid #ddd", display: "flex", gap: 16 }}>
        <Link to="/" style={{ fontWeight: 600, textDecoration: "none" }}>MACR Run Viewer</Link>
        <Link to="/launch" style={{ textDecoration: "none" }}>+ New run</Link>
      </header>
      <main style={{ padding: 16 }}>
        <Routes>
          <Route path="/" element={<RunList />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/launch" element={<LaunchForm />} />
          <Route path="/live" element={<LiveRun />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
