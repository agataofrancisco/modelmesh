# Revisão de segurança (tarefa 9.4)

Âmbito: chaves, administração, proxy aberto, redacção e fail-closed. Esta revisão é uma verificação
do próprio autor com os testes do repositório; **não substitui uma revisão independente**.

| Área | Verificação | Evidência | Estado |
|---|---|---|---|
| Chaves em claro | só o hash SHA-256 e o prefixo são guardados | `auth/keys.py`; `test_key_shown_once_and_only_prefix_listed` | resolvido |
| Chave mostrada uma vez | `POST /admin/keys` com `cache-control: no-store`; listagens sem a chave | `api/admin.py:create_key` | resolvido |
| Chave revogada | `401` imediato | `test_revoked_key_gets_401` | resolvido |
| Admin separado | token próprio; chave de inferência em `/admin` = `403` | `test_inference_key_cannot_access_admin`, `test_admin_requires_token` | resolvido |
| Admin sem token configurado | fechado (`401`) | `auth/dependencies.py:require_admin` | resolvido |
| Proxy aberto | sem chave válida, `401` e zero chamadas a providers | `test_no_key_is_401_and_never_contacts_provider` | resolvido |
| Modelo fora da política | `403`, sem chamada a provider | `test_model_not_allowed_is_403_without_provider_call` | resolvido |
| Redacção de dados pessoais | nenhum conteúdo guardado; redacção de padrões nos logs | `test_usage_record_has_no_message_content_and_aggregates`, `test_redaction_removes_email_phone_and_keys` | resolvido |
| Chaves de providers | lidas do ambiente pelo nome (`api_key_env`), nunca registadas | `providers/openai_compatible.py:_headers` | resolvido |
| Fail-closed | Redis em baixo recusa pedidos | `test_redis_down_fails_closed_with_503` | resolvido |
| Validação de entrada | corpo com limite, JSON, schema, `max_tokens` | `api/inference.py`; `test_max_tokens_above_policy_rejected` | resolvido |
| Erros sem detalhe interno | o envelope só leva motivo e hops (provider, modelo, resultado) | `errors.py`; `test_all_hops_fail_is_503_upstream_unavailable` | resolvido |

## Achados que ficam documentados (não resolvidos nesta change)

1. **`/metrics` não tem autenticação própria.** Depende de a rede ser privada. O `docker-compose.yml`
   não publica a porta do gateway. **Risco**: se o proxy de entrada expuser `/metrics`, revelam-se
   nomes de equipas e modelos.
2. **`/admin/mocks/{name}/profile` encaminha para `control_url`.** Serve o testador de failover, mas
   permite alterar o comportamento de um provider. **Mitigação**: em produção, não configurar
   `control_url`. Recomenda-se remover a rota ou protegê-la por um papel separado.
3. **Token de administração estático**, sem rotação nem múltiplos operadores. **Recomendação**:
   um segredo por operador ou um IdP, em fase posterior.
4. **Token de admin no navegador**: o painel guarda-o em `sessionStorage` (por separador) e não em
   `localStorage`. Continua a ser legível por JavaScript na página. **Mitigação**: o painel deve
   ficar atrás de SSO/rede privada.
5. **Sem limite de taxa nas rotas de administração.** Um atacante com o token de admin podia
   esgotar o Postgres com escritas. Aceitável para uma rede de administração privada.
6. **Chaves de inferência não têm expiração.** Recomenda-se rotação periódica por política.
7. **Sem rotação da chave de cifra** (não aplicável: o hash não tem chave).

## Dependências

Versões fixadas em `pyproject.toml` e em `requirements.txt`. Não houve análise de vulnerabilidades
(SCA) neste ambiente: `TODO: correr pip-audit` antes da entrega.

## Revisão independente do supervisor (2026-11-21)

Verificado no código, depois da auto-revisão acima:

- **Admin:** os routers `/admin` têm `Depends(require_admin)` ao nível do router (`gateway/app/api/admin.py:19`, `admin_ops.py:21`). A comparação é feita em tempo constante (`hmac.compare_digest`) e, sem token configurado, a administração fica fechada.
- **Chaves virtuais:** só se guarda o `sha256` e o prefixo (`gateway/app/auth/keys.py:43`).
- **Fail-closed:** quando o Redis falha, o pedido é recusado (`gateway/app/pipeline.py:112`) em vez de servir sem limites.
- **Proxy de controlo dos mocks** (`admin_ops.py:112`): exige admin e só contacta `control_url` configurados, nunca URLs vindos do pedido, o que limita o risco de SSRF. **Não** deve existir configuração com `control_url` em produção.
- **`/metrics`:** não tem autenticação na aplicação. A protecção depende do deployment (rede privada), como a spec permite. É um risco residual se o serviço for exposto directamente.
- **Por verificar na data desta revisão:** a atomicidade em Redis real (tarefa 5.1) e o `pip-audit`.

Atualização de 2026-11-24: a tarefa 5.1 passou contra Redis 7.4.11 real (`pytest -m redis`:
`1 passed, 56 deselected`). A análise de dependências com `pip-audit` continua pendente.
