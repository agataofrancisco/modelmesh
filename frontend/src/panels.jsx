import React, { useEffect, useState, useCallback } from "react";
import { api } from "./api.js";

function useLoader(load, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    setError("");
    load()
      .then(setData)
      .catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, reload };
}

// Estimativa de percentil a partir dos buckets cumulativos do histograma Prometheus.
export function quantileFromBuckets(buckets, q) {
  if (!buckets.length) return null;
  const total = buckets[buckets.length - 1].count;
  if (total === 0) return null;
  const target = q * total;
  for (let i = 0; i < buckets.length; i += 1) {
    if (buckets[i].count >= target) return buckets[i].le;
  }
  return buckets[buckets.length - 1].le;
}

export function parseLatencyBuckets(metricsText) {
  const buckets = [];
  for (const line of String(metricsText || "").split("\n")) {
    if (!line.startsWith("modelmesh_latency_seconds_bucket{")) continue;
    const match = line.match(/le="([^"]+)"\}\s+([0-9.eE+-]+)/);
    if (!match) continue;
    const le = match[1] === "+Inf" ? Infinity : Number(match[1]);
    buckets.push({ le, count: Number(match[2]) });
  }
  return buckets.sort((a, b) => a.le - b.le);
}

export function TeamsKeys({ ctx }) {
  const teams = useLoader(() => api("/admin/teams", { token: ctx.token }), [ctx.token]);
  const keys = useLoader(() => api("/admin/keys", { token: ctx.token }), [ctx.token]);
  const [teamForm, setTeamForm] = useState({ id: "", name: "" });
  const [keyForm, setKeyForm] = useState({ team_id: "", name: "", rpm_limit: "", budget_usd: "" });
  const [issued, setIssued] = useState(null);

  async function createTeam(event) {
    event.preventDefault();
    try {
      await api("/admin/teams", { method: "POST", token: ctx.token, body: teamForm });
      ctx.notify(`Equipa ${teamForm.id} criada.`);
      setTeamForm({ id: "", name: "" });
      teams.reload();
    } catch (err) {
      ctx.notify(err.message);
    }
  }

  async function createKey(event) {
    event.preventDefault();
    const body = { team_id: keyForm.team_id, name: keyForm.name };
    if (keyForm.rpm_limit) body.rpm_limit = Number(keyForm.rpm_limit);
    if (keyForm.budget_usd) body.budget_usd = keyForm.budget_usd;
    try {
      const created = await api("/admin/keys", { method: "POST", token: ctx.token, body });
      setIssued(created);
      keys.reload();
    } catch (err) {
      ctx.notify(err.message);
    }
  }

  async function revoke(id) {
    try {
      await api(`/admin/keys/${id}/revoke`, { method: "POST", token: ctx.token });
      keys.reload();
    } catch (err) {
      ctx.notify(err.message);
    }
  }

  return (
    <div className="grid">
      <section className="card">
        <h2>Equipas</h2>
        {teams.error && <p className="error">{teams.error}</p>}
        <ul>
          {(teams.data?.data || []).map((t) => (
            <li key={t.id}>
              <code>{t.id}</code> · {t.name}
            </li>
          ))}
        </ul>
        <form onSubmit={createTeam} className="stack">
          <input placeholder="id (ex.: suporte)" value={teamForm.id}
            onChange={(e) => setTeamForm({ ...teamForm, id: e.target.value })} required />
          <input placeholder="nome" value={teamForm.name}
            onChange={(e) => setTeamForm({ ...teamForm, name: e.target.value })} required />
          <button type="submit">Criar equipa</button>
        </form>
      </section>

      <section className="card">
        <h2>Chaves de inferência</h2>
        {keys.error && <p className="error">{keys.error}</p>}
        <table>
          <thead>
            <tr><th>Prefixo</th><th>Equipa</th><th>Estado</th><th></th></tr>
          </thead>
          <tbody>
            {(keys.data?.data || []).map((k) => (
              <tr key={k.id}>
                <td><code>{k.prefix}</code></td>
                <td>{k.team_id}</td>
                <td>{k.status}</td>
                <td>
                  {k.status === "active" && (
                    <button className="ghost" onClick={() => revoke(k.id)}>Revogar</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <form onSubmit={createKey} className="stack">
          <input placeholder="equipa" value={keyForm.team_id}
            onChange={(e) => setKeyForm({ ...keyForm, team_id: e.target.value })} required />
          <input placeholder="nome da chave" value={keyForm.name}
            onChange={(e) => setKeyForm({ ...keyForm, name: e.target.value })} required />
          <input placeholder="RPM (opcional)" value={keyForm.rpm_limit}
            onChange={(e) => setKeyForm({ ...keyForm, rpm_limit: e.target.value })} />
          <input placeholder="orçamento USD (opcional)" value={keyForm.budget_usd}
            onChange={(e) => setKeyForm({ ...keyForm, budget_usd: e.target.value })} />
          <button type="submit">Emitir chave</button>
        </form>
        {issued && (
          <div className="issued">
            <p>Chave mostrada <strong>uma única vez</strong>. Copie-a agora:</p>
            <code className="secret">{issued.key}</code>
            <button className="ghost" onClick={() => setIssued(null)}>Já copiei</button>
          </div>
        )}
      </section>
    </div>
  );
}

export function PolicyEditor({ ctx }) {
  const [team, setTeam] = useState("");
  const [text, setText] = useState("");
  const [version, setVersion] = useState(null);

  async function load() {
    try {
      const data = await api(`/admin/policies/${encodeURIComponent(team)}`, { token: ctx.token });
      setText(JSON.stringify(data.policy, null, 2));
      setVersion(data.version);
    } catch (err) {
      ctx.notify(err.message);
    }
  }

  async function save() {
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      ctx.notify("JSON inválido: a política anterior mantém-se.");
      return;
    }
    try {
      const data = await api(`/admin/policies/${encodeURIComponent(team)}`, {
        method: "PUT", token: ctx.token, body,
      });
      setVersion(data.version);
      ctx.notify(`Política guardada (versão ${data.version}).`);
    } catch (err) {
      // O texto do editor NÃO é apagado: o admin corrige e volta a submeter.
      ctx.notify(`Rejeitada: ${err.message}. A versão anterior mantém-se.`);
    }
  }

  return (
    <section className="card">
      <h2>Políticas por equipa</h2>
      <div className="row">
        <input placeholder="equipa" value={team} onChange={(e) => setTeam(e.target.value)} />
        <button onClick={load}>Carregar</button>
        <button onClick={save} disabled={!team}>Guardar política</button>
        {version !== null && <span className="hint">versão atual: {version}</span>}
      </div>
      <textarea rows={22} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
    </section>
  );
}

export function UsageBudgets({ ctx }) {
  const usage = useLoader(
    () => api("/admin/usage?group_by=team&days=7", { token: ctx.token }), [ctx.token]);
  const [team, setTeam] = useState("");
  const [budget, setBudget] = useState(null);
  const metrics = useLoader(async () => {
    const response = await fetch("/metrics");
    return { text: await response.text() };
  }, []);

  async function loadBudget() {
    try {
      setBudget(await api(`/admin/budgets?team=${encodeURIComponent(team)}`, { token: ctx.token }));
    } catch (err) {
      ctx.notify(err.message);
    }
  }

  const buckets = parseLatencyBuckets(metrics.data?.text);
  const p50 = quantileFromBuckets(buckets, 0.5);
  const p95 = quantileFromBuckets(buckets, 0.95);

  return (
    <div className="grid">
      <section className="card">
        <h2>Consumo (7 dias, por equipa)</h2>
        {usage.error && <p className="error">{usage.error}</p>}
        <table>
          <thead><tr><th>Equipa</th><th>Pedidos</th><th>Tokens in/out</th><th>Custo real USD</th></tr></thead>
          <tbody>
            {(usage.data?.data || []).map((row) => (
              <tr key={row.group}>
                <td>{row.group}</td><td>{row.requests}</td>
                <td>{row.tokens_in}/{row.tokens_out}</td><td>{row.cost_real_usd}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3>Latência (estimativa a partir do histograma)</h3>
        <p>
          p50 ≤ {p50 === null ? "—" : `${(p50 * 1000).toFixed(0)} ms`} ·
          p95 ≤ {p95 === null ? "—" : `${(p95 * 1000).toFixed(0)} ms`}
        </p>
      </section>

      <section className="card">
        <h2>Orçamento mensal da equipa</h2>
        <div className="row">
          <input placeholder="equipa" value={team} onChange={(e) => setTeam(e.target.value)} />
          <button onClick={loadBudget} disabled={!team}>Consultar</button>
        </div>
        {budget && (
          <ul>
            <li>Período: {budget.period}</li>
            <li>Limite: {budget.budget_usd_monthly ?? "sem limite"} USD</li>
            <li>Gasto: {budget.spent_usd} USD</li>
            <li>Reservado em curso: {budget.reserved_usd} USD</li>
          </ul>
        )}
      </section>
    </div>
  );
}

export function CircuitsRoutes({ ctx }) {
  const circuits = useLoader(() => api("/admin/circuits", { token: ctx.token }), [ctx.token]);
  const [team, setTeam] = useState("");
  const [routes, setRoutes] = useState(null);

  async function loadRoutes() {
    try {
      setRoutes(await api(`/admin/routes?team=${encodeURIComponent(team)}`, { token: ctx.token }));
    } catch (err) {
      ctx.notify(err.message);
    }
  }

  return (
    <div className="grid">
      <section className="card">
        <h2>Estado dos circuitos</h2>
        {circuits.error && <p className="error">{circuits.error}</p>}
        <table>
          <thead><tr><th>Provider</th><th>Modelo</th><th>Estado</th></tr></thead>
          <tbody>
            {(circuits.data?.data || []).map((c) => (
              <tr key={`${c.provider}/${c.model}`}>
                <td>{c.provider}</td><td>{c.model}</td><td>{c.state}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="ghost" onClick={circuits.reload}>Atualizar</button>
      </section>

      <section className="card">
        <h2>Rotas efectivas por equipa</h2>
        <div className="row">
          <input placeholder="equipa" value={team} onChange={(e) => setTeam(e.target.value)} />
          <button onClick={loadRoutes} disabled={!team}>Ver rotas</button>
        </div>
        {routes && (
          <ul>
            {routes.routes.map((r) => (
              <li key={r.requested}>
                <code>{r.requested}</code> → {r.served_model}:{" "}
                {r.chain.map((h) => `${h.provider}/${h.model}`).join(" → ")}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export function FailoverTester({ ctx }) {
  const [mock, setMock] = useState("mock_a");
  const [errorRate, setErrorRate] = useState(1);
  const [inferenceKey, setInferenceKey] = useState("");
  const [model, setModel] = useState("mock-small");
  const [results, setResults] = useState([]);

  async function applyFailures() {
    try {
      await api(`/admin/mocks/${mock}/profile`, {
        method: "PUT", token: ctx.token, body: { error_rate: Number(errorRate), seed: 1 },
      });
      ctx.notify(`Mock ${mock}: taxa de erro ${errorRate}.`);
    } catch (err) {
      ctx.notify(err.message);
    }
  }

  async function runTests() {
    const out = [];
    for (let i = 0; i < 5; i += 1) {
      const started = performance.now();
      try {
        const response = await fetch("/v1/chat/completions", {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${inferenceKey}` },
          body: JSON.stringify({ model, messages: [{ role: "user", content: "teste de failover" }],
            max_tokens: 8 }),
        });
        out.push({
          status: response.status,
          path: response.headers.get("x-modelmesh-fallback-path") || "—",
          ms: Math.round(performance.now() - started),
        });
      } catch (err) {
        out.push({ status: "rede", path: err.message, ms: 0 });
      }
    }
    setResults(out);
  }

  return (
    <section className="card">
      <h2>Testador de failover</h2>
      <p className="hint">
        Força falhas num mock e envia pedidos de teste com uma chave de inferência de uma equipa.
        A chave fica só em memória e não é guardada.
      </p>
      <div className="row">
        <select value={mock} onChange={(e) => setMock(e.target.value)}>
          <option value="mock_a">mock_a</option>
          <option value="mock_b">mock_b</option>
        </select>
        <label>taxa de erro {errorRate}</label>
        <input type="range" min="0" max="1" step="0.1" value={errorRate}
          onChange={(e) => setErrorRate(e.target.value)} />
        <button onClick={applyFailures}>Aplicar falhas</button>
      </div>
      <div className="row">
        <input type="password" placeholder="chave mm_live_… (só para o teste)" value={inferenceKey}
          onChange={(e) => setInferenceKey(e.target.value)} autoComplete="off" />
        <select value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="mock-small">mock-small</option>
          <option value="mock-large">mock-large</option>
        </select>
        <button onClick={runTests} disabled={!inferenceKey}>Enviar 5 pedidos</button>
      </div>
      {results.length > 0 && (
        <table>
          <thead><tr><th>#</th><th>Estado</th><th>Caminho</th><th>ms</th></tr></thead>
          <tbody>
            {results.map((r, i) => (
              <tr key={i}><td>{i + 1}</td><td>{r.status}</td><td>{r.path}</td><td>{r.ms}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
