# 02 · Chaves virtuais, hash e administração separada

## O problema

Cada equipa precisa de uma credencial própria. Se a base de dados vazar, as chaves não podem ser
usadas. Se uma chave de inferência conseguir criar equipas, o gateway deixa de ser controlado.

## O que entra e o que sai

Emissão (`POST /admin/keys`) devolve a chave em claro **uma única vez**. Consultas posteriores
mostram só o prefixo. Formato da chave: `mm_live_` + 32 caracteres base62 aleatórios
(`gateway/app/auth/keys.py:generate_key`). O prefixo mostrado tem 16 caracteres
(`mm_live_` + 8 aleatórios), por exemplo `mm_live_UXGbWrUQ`.

Saída real da listagem (`GET /admin/keys`), sem a chave nem o hash:

```text
prefix=mm_live_UXGbWrUQ  team=suporte  status=active
```

## Como funciona por dentro

- Guarda-se `sha256(chave)` (`keys.py:hash_key`) e o prefixo. A base de dados nunca vê a chave.
- A autenticação calcula o hash do Bearer recebido e procura-o (`auth/dependencies.py:authenticate_inference`).
- Admin usa um token separado (`MODELMESH_ADMIN_TOKEN`), comparado com `hmac.compare_digest`
  (`auth/dependencies.py:require_admin`).
- Uma chave de inferência em `/admin/*` devolve `403 forbidden`: o formato `mm_live_` é reconhecido
  e recusado (`looks_like_virtual_key`).
- Revogação marca `status=revoked`. Como cada pedido consulta a base, a revogação é imediata.

## Porquê esta escolha

- **SHA-256 e não bcrypt/argon2**: bcrypt/argon2 protegem palavras-passe humanas, que têm entropia
  baixa e precisam de custo contra adivinhação. Uma chave com 32 caracteres base62 tem cerca de 190
  bits de entropia: não há dicionário para atacar, e um hash rápido é suficiente.
- **Admin separado**: uma chave de equipa comprometida não pode criar outras equipas nem mudar
  políticas.
- **Prefixo de 16 caracteres**: identifica a chave nos logs e na administração sem revelar o
  segredo (8 caracteres aleatórios não permitem reconstruir a chave).

## Alternativas

- Chaves assinadas (JWT): não permitem revogação imediata sem uma lista de bloqueio.
- Guardar a chave cifrada: obriga a gerir uma chave de cifra; o hash não precisa de nenhuma.

## Como falha

- Chave revogada: `401 invalid_api_key`. Teste: `test_revoked_key_gets_401`.
- Chave de inferência na administração: `403 forbidden`. Teste:
  `test_inference_key_cannot_access_admin`. Resposta real:
  `{"error":{"message":"uma chave de inferência não acede à administração","type":"permission_error","code":"forbidden", ...}}`
- Chave mostrada uma só vez: `test_key_shown_once_and_only_prefix_listed`.

## Perguntas de entrevista

1. **Porque não bcrypt para chaves de API?** Porque a entropia é alta e o custo só atrasaria cada
   pedido. A pergunta certa é "qual é a entropia do segredo?", não "qual é o algoritmo da moda".
2. **Como se revoga uma chave sem reiniciar nada?** Estado na base de dados, consultado a cada
   pedido. O custo é uma consulta por pedido; num sistema maior colocava-se uma cache curta.
3. **Porque é que a administração não aceita a chave de inferência de admin?** Separação de
   privilégios: são papéis diferentes e o erro deve ser explícito (`403`, não `401`).
