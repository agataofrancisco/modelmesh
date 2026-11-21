# ModelMesh

Gateway compatível com a API da OpenAI que centraliza autenticação por equipa, política de routing,
limites, orçamentos, fallback e observabilidade. Projeto de portefólio: os providers reais são
opcionais e os testes usam providers simulados.

Documentação de aprendizagem em `docs/learn/` (começa em `00-visao-geral.md`). Arquitetura em
`docs/architecture.md`, decisões em `docs/decisions.md`, revisão de segurança em
`docs/security-review.md`.

## Requisitos

- Python 3.12 e Node.js 22 (painel).
- Sem Docker é possível correr tudo localmente. O Redis real é opcional (ver testes).

## Instalação

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install pytest==9.2.0 pytest-asyncio==1.5.0 "fakeredis[lua]==2.40.0" lupa==2.8 pgserver==0.1.4 openai==3.57.0 ruff==0.17.6
```

## Configuração

Copie `.env.example` para `.env` **localmente** (não é versionado) e defina `MODELMESH_ADMIN_TOKEN`.
Nunca commite `.env`.

## Migrações e dados demo

```bash
set MODELMESH_DATABASE_URL=sqlite+aiosqlite:///./.runtime/modelmesh.db
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m gateway.app.store.seed
```

O seed cria as equipas `suporte`, `marketing` e `dados`, políticas demo e preços fictícios. Não cria
chaves: as chaves são emitidas pela administração e mostradas uma única vez.

## Correr o gateway

Os providers mock são servidores separados:

```bash
.venv\Scripts\python -m gateway.app.providers.mock_server --name mock_a --port 9001
.venv\Scripts\python -m gateway.app.providers.mock_server --name mock_b --port 9002
.venv\Scripts\python -m uvicorn gateway.app.asgi:app --port 8000
```

Emitir uma chave e fazer um pedido (exemplo com o SDK oficial):

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="mm_live_...")
client.chat.completions.create(model="cheap", messages=[{"role": "user", "content": "olá"}])
```

## Painel de administração

```bash
cd frontend
npm install
MODELMESH_API=http://127.0.0.1:8000 npm run dev
```

Abra `http://localhost:5173` e introduza o token de administração.

## Testes

```bash
.venv\Scripts\python -m pytest -q          # rápidos + PostgreSQL real (pgserver)
.venv\Scripts\python -m pytest -m redis    # exige Redis real em MODELMESH_TEST_REDIS_URL
.venv\Scripts\python -m ruff check gateway tests chaos bench
```

Marcadores: `redis` (Redis real; ignorado se indisponível), `postgres` (PostgreSQL real com
pgserver). Os testes de concorrência sem `redis` usam fakeredis em processo ou um servidor fakeredis
TCP, e estão rotulados como tal.

## Chaos e benchmark

```bash
.venv\Scripts\python -m chaos.run_chaos        # 8 cenários com asserções; exit 1 se algum falhar
.venv\Scripts\python -m bench.bench_overhead   # overhead directo vs gateway (mock, localhost)
```

Os relatórios ficam em `chaos/results/` e `bench/results/`, com `providers: mock`, plataforma, data e
commit.

## Estado

Ver `docs/case-study.md` para o que está verificado e o que está pendente (Redis real, Docker,
providers reais).

## Licença

Projeto de portefólio. Sem licença definida.
