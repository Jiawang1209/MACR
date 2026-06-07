import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { RunList } from "./RunList";
import { RunDetail } from "./RunDetail";

export function App() {
  return (
    <BrowserRouter>
      <header style={{ padding: "12px 16px", borderBottom: "1px solid #ddd" }}>
        <Link to="/" style={{ fontWeight: 600, textDecoration: "none" }}>MACR Run Viewer</Link>
      </header>
      <main style={{ padding: 16 }}>
        <Routes>
          <Route path="/" element={<RunList />} />
          <Route path="/runs/:id" element={<RunDetail />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
