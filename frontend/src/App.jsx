import React, { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api.js";
import { TeamsKeys, PolicyEditor, UsageBudgets, CircuitsRoutes, FailoverTester } from "./panels.jsx";

const TABS = [
  { id: "teams", label: "Equipas e chaves" },
  { id: "policies", label: "Políticas" },
  { id: "usage", label: "Consumo e orçamentos" },
  { id: "circuits", label: "Circuitos e rotas" },
  { id: "failover", label: "Testador de failover" },
];

export default function App() {
  const [token, setTokenState] = useState(getToken());
  const [tab, setTab] = useState("teams");
  const [health, setHealth] = useState(null);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api("/health/ready", { token: "" })
      .then(setHealth)
      .catch((err) => setHealth({ status: "indisponível", checks: { erro: err.message } }));
  }, []);

  function saveToken(value) {
    setToken(value);
    setTokenState(value);
    setNotice(value ? "Token guardado nesta sessão do separador." : "Token removido.");
  }

  const ctx = { token, notify: setNotice };

  return (
    <div className="shell">
      <header>
        <h1>ModelMesh · Painel de administração</h1>
        <div className="health">
          Estado do gateway: <strong>{health ? health.status : "a verificar…"}</strong>
        </div>
      </header>

      <section className="card">
        <label htmlFor="token">Token de administração</label>
        <div className="row">
          <input
            id="token"
            type="password"
            autoComplete="off"
            defaultValue={token}
            placeholder="MODELMESH_ADMIN_TOKEN"
            onKeyDown={(e) => {
              if (e.key === "Enter") saveToken(e.currentTarget.value);
            }}
          />
          <button onClick={() => saveToken(document.getElementById("token").value)}>Guardar</button>
          <button className="ghost" onClick={() => saveToken("")}>Limpar</button>
        </div>
        <p className="hint">
          Só para administração. Uma chave de inferência (mm_live_…) é recusada aqui com 403.
        </p>
        {notice && <p className="notice">{notice}</p>}
      </section>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "teams" && <TeamsKeys ctx={ctx} />}
      {tab === "policies" && <PolicyEditor ctx={ctx} />}
      {tab === "usage" && <UsageBudgets ctx={ctx} />}
      {tab === "circuits" && <CircuitsRoutes ctx={ctx} />}
      {tab === "failover" && <FailoverTester ctx={ctx} />}
    </div>
  );
}
