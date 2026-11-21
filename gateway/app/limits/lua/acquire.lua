-- Rate limit atómico para dois âmbitos (chave e equipa) num único script.
-- Verifica TODOS os limites e só depois incrementa. Ou tudo, ou nada.
--
-- KEYS (6): rpm_k, tpm_k, conc_k, rpm_t, tpm_t, conc_t   (cada âmbito: RPM, TPM, concorrência)
-- ARGV: 1 now_ms | 2 window_ms | 3 tpm_key_ttl_ms | 4 est_tokens | 5 member | 6 conc_ttl_ms
--       7 rpm_limit_k | 8 tpm_limit_k | 9 conc_limit_k | 10 rpm_limit_t | 11 tpm_limit_t | 12 conc_limit_t
-- Limite 0 = sem limite.
-- Devolve {allowed (0|1), reason, retry_after_ms}.
-- reason: 0 ok; 1/2/3 = rpm/tpm/concorrência da chave; 4/5/6 = rpm/tpm/concorrência da equipa.

local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local tpm_ttl = tonumber(ARGV[3])
local est = tonumber(ARGV[4])
local member = ARGV[5]
local conc_ttl = tonumber(ARGV[6])

local rpm_limits = { tonumber(ARGV[7]), tonumber(ARGV[10]) }
local tpm_limits = { tonumber(ARGV[8]), tonumber(ARGV[11]) }
local conc_limits = { tonumber(ARGV[9]), tonumber(ARGV[12]) }

-- Fase 1: verificação sem efeitos colaterais.
for s = 1, 2 do
  local rk = KEYS[(s - 1) * 3 + 1]
  local tk = KEYS[(s - 1) * 3 + 2]
  local ck = KEYS[(s - 1) * 3 + 3]
  local offset = (s - 1) * 3

  if rpm_limits[s] > 0 then
    redis.call('ZREMRANGEBYSCORE', rk, 0, now - window)
    local count = redis.call('ZCARD', rk)
    if count + 1 > rpm_limits[s] then
      local oldest = redis.call('ZRANGE', rk, 0, 0, 'WITHSCORES')
      local retry = 1000
      if oldest[2] then
        retry = math.max(1, tonumber(oldest[2]) + window - now)
      end
      return { 0, offset + 1, retry }
    end
  end

  if tpm_limits[s] > 0 then
    local used = tonumber(redis.call('GET', tk) or '0')
    if used + est > tpm_limits[s] then
      -- Retry: até ao início do próximo minuto (o contador TPM é por minuto).
      return { 0, offset + 2, 60000 - (now % 60000) }
    end
  end

  if conc_limits[s] > 0 then
    local current = tonumber(redis.call('GET', ck) or '0')
    if current + 1 > conc_limits[s] then
      return { 0, offset + 3, 1000 }
    end
  end
end

-- Fase 2: aplicar (só chegamos aqui se todos os âmbitos passaram).
for s = 1, 2 do
  local rk = KEYS[(s - 1) * 3 + 1]
  local tk = KEYS[(s - 1) * 3 + 2]
  local ck = KEYS[(s - 1) * 3 + 3]

  if rpm_limits[s] > 0 then
    redis.call('ZADD', rk, now, member)
    redis.call('PEXPIRE', rk, window * 2)
  end
  if tpm_limits[s] > 0 then
    redis.call('INCRBY', tk, est)
    redis.call('PEXPIRE', tk, tpm_ttl)
  end
  if conc_limits[s] > 0 then
    redis.call('INCR', ck)
    redis.call('PEXPIRE', ck, conc_ttl)
  end
end

return { 1, 0, 0 }
