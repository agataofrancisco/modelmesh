-- Regista o resultado de uma tentativa e actualiza o estado do circuito.
-- Abre quando, na janela, há >= min_requests pedidos e a taxa de falhas >= ratio.
-- Half-open: sucesso fecha; falha reabre com novo cooldown.
--
-- KEYS: 1 hash | 2 zset de todos os resultados | 3 zset de falhas | 4 chave do probe
-- ARGV: 1 now_ms | 2 window_ms | 3 min_requests | 4 failure_ratio | 5 cooldown_ms | 6 ok (1|0) | 7 member
-- Devolve: 'closed' | 'open' | 'half_open'

local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local min_requests = tonumber(ARGV[3])
local ratio = tonumber(ARGV[4])
local cooldown = tonumber(ARGV[5])
local ok = ARGV[6] == '1'
local member = ARGV[7]

local state = redis.call('HGET', KEYS[1], 'state') or 'closed'

-- Resultados de pedidos que partiram antes da abertura não alteram um circuito já aberto.
if state == 'open' then
  return 'open'
end

redis.call('ZREMRANGEBYSCORE', KEYS[2], 0, now - window)
redis.call('ZREMRANGEBYSCORE', KEYS[3], 0, now - window)
redis.call('ZADD', KEYS[2], now, member)
if not ok then
  redis.call('ZADD', KEYS[3], now, member)
end
redis.call('PEXPIRE', KEYS[2], window * 2)
redis.call('PEXPIRE', KEYS[3], window * 2)

if state == 'half_open' then
  redis.call('DEL', KEYS[4])
  if ok then
    redis.call('HSET', KEYS[1], 'state', 'closed')
    redis.call('DEL', KEYS[2], KEYS[3])
    return 'closed'
  end
  redis.call('HSET', KEYS[1], 'state', 'open', 'opened_until', now + cooldown)
  return 'open'
end

if not ok then
  local total = redis.call('ZCARD', KEYS[2])
  local failures = redis.call('ZCARD', KEYS[3])
  if total >= min_requests and failures / total >= ratio then
    redis.call('HSET', KEYS[1], 'state', 'open', 'opened_until', now + cooldown)
    redis.call('DEL', KEYS[2], KEYS[3])
    return 'open'
  end
end
return 'closed'
