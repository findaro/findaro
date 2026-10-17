import { createClient, debounce } from "@findaro/sdk";
import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

const findaro = createClient({ projectId: import.meta.env.VITE_FINDARO_PROJECT,
  searchKey: import.meta.env.VITE_FINDARO_KEY, baseUrl: import.meta.env.VITE_FINDARO_URL });

function App() {
  const [query, setQuery] = useState("");
  const [res, setRes] = useState(null);
  const [answer, setAnswer] = useState("");
  const [session, setSession] = useState(null);
  const run = useMemo(() => debounce((q, patch) =>
    findaro.search({ query: q, patch }).then(setRes).catch((e) => e.name !== "AbortError" && console.error(e)), 250), []);

  const ask = async () => {
    setAnswer("");
    const turn = findaro.chat(query, { sessionId: session, onText: (_, full) => setAnswer(full),
      onResults: (r) => setRes((prev) => ({ ...prev, hits: r.items, total: r.total })) });
    const out = await turn.result;
    setSession(out.sessionId);
    if (out.plan?.understood) setRes((prev) => ({ ...prev, understood: out.plan.understood }));
  };

  return (
    <main style={{ maxWidth: 900, margin: "24px auto", fontFamily: "system-ui", padding: 16 }}>
      <input value={query} placeholder="Search or ask…" style={{ width: "70%", padding: 8 }}
        onChange={(e) => { setQuery(e.target.value); if (e.target.value.length > 1) run(e.target.value); }} />
      <button onClick={ask} style={{ marginLeft: 8, padding: 8 }}>Ask AI</button>
      <p>{res?.understood?.chips?.map((c) => (
        <button key={c.label} onClick={() => run(query, c.remove)} style={{ marginRight: 6 }}>{c.label} ×</button>))}
      </p>
      {answer && <p data-testid="answer">{answer}</p>}
      <p>{res ? `${res.total} results` : ""}</p>
      <ul>{res?.hits?.map((h) => <li key={h.id}>{h.document.title} — ₹{h.document.price}</li>)}</ul>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
