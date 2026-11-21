# Decisões de arquitetura

## D1 · FastAPI assíncrono com httpx
Um pedido passa a maior parte do tempo à espera do provider. `async` permite muitas esperas com
poucos processos. Go seria mais rápido, mas a velocidade de desenvolvimento e a coerência do
portefólio pesaram. O overhead é medido em `docs/learn/10`.

## D2 · Adaptadores próprios e taxonomia de erros
O policy engine decide por `kind` (`transient`, `timeout`, `auth`, `invalid_response`, `client`),
nunca por texto de erro de um provider. Ver `gateway/app/providers/base.py`.

## D3 · Lua no Redis para limites
Atomicidade sem transações. Janela deslizante para RPM (precisão), contador por minuto para TPM,
contador com `DECR` e TTL para concorrência. Ver `docs/learn/06`.

## D4 · Orçamento: reserva no Redis, verdade no Postgres
Reserva antes do provider, reconciliação depois, sweeper para órfãs. O Postgres é a fonte e
`rebuild_spent` reconstrói o Redis. Ver `docs/learn/07`.

## D5 · Circuit breaker partilhado em Redis
Estado `closed`/`open`/`half_open`, abertura por taxa e volume, um probe em half-open. Ver `docs/learn/05`.

## D6 · Retries com jitter e deadline
`min(cap, base·2^n)·U(0.5,1.5)`, `Retry-After` como mínimo, nunca além do deadline total. Ver `docs/learn/04`.

## D7 · Preços versionados em micro-USD
Vigência por `effective_date`, contadores inteiros, arredondamento conservador. Ver `docs/learn/08`.

## D8 · Chaves: SHA-256 com prefixo de 16 caracteres
Entropia alta dispensa bcrypt/argon2. O prefixo tem o literal `mm_live_` mais 8 caracteres
(decisão nova: o plano não fixava o tamanho; 8 caracteres aleatórios chegam para identificar sem
expor). Ver `docs/learn/02`.

## D9 · Métricas com prefixo `modelmesh_` e registo próprio
Os nomes da spec (`request_total`, `fallback_total`, ...) ganham o prefixo `modelmesh_` para
evitar colisões com outras métricas no mesmo Prometheus (decisão nova). Registo por aplicação para
testes isolados.

## D10 · Fail-closed por omissão
Sem Redis, recusa-se. A alternativa (servir sem limites) foi rejeitada porque o gateway existe para
controlar custo.

## D11 · Honestidade nos números
Relatórios de chaos e benchmark trazem `providers: mock`, plataforma, data, commit e limitações.
Não há extrapolação para providers reais.

## Decisões novas tomadas na implementação (não previstas no plano)

- **Header de caminho de fallback** usa `->` e não `→`: os cabeçalhos HTTP são ASCII/latin-1.
- **Período de orçamento mensal (UTC, `YYYYMM`)**. O plano falava em orçamento sem período.
- **Orçamento de equipa e limites de tráfego vivem na política**; a chave só tem limites próprios
  opcionais mais restritivos (o efetivo é o mínimo implícito pelas duas verificações).
- **Sem conteúdo de mensagens em lado nenhum**, por isso a "flag de debug por equipa" da spec não
  foi implementada (fica como não implementado; a redacção de padrões existe em
  `accounting/redaction.py` como defesa adicional).
- **Órfãs são cobradas pela estimativa** (limite superior), e não libertadas a zero, para não
  subcontar um pedido que já chamou o provider. O evento de log mantém o nome da spec.
- **Erro do cliente do provider** devolve `400 upstream_client_error` (código extra, fora da lista
  estável da spec), documentado no catálogo de erros.
- **Pedido com `pricing_missing`** devolve `503`, não `422`: é um problema de configuração do
  servidor, não do cliente.
- **`/admin/mocks/{name}/profile`** encaminha a configuração de falhas para o mock. Serve o testador
  de failover do painel. Em produção o `control_url` não deve estar configurado (ver
  `docs/security-review.md`).
- **Migração `0001`** gerada pelo Alembic a partir dos modelos e revista à mão.

## Fronteira com o LiteLLM

O que é do ModelMesh: autenticação por equipa com chaves virtuais, policy engine declarativo,
circuito partilhado, rate limit e orçamento atómicos em Redis, reconciliação com registo de uso e
testes de chaos com asserções.

O que poderia vir do LiteLLM: a normalização de formatos de muitos providers. Caberia atrás de
`ProviderAdapter`, sem alterar o policy engine, porque este só conhece a taxonomia de erros.
Não foi integrado nesta change.
