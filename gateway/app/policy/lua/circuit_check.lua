-- Decide se um hop pode ser chamado. Estados: closed | open(opened_until) | half_open.
-- Em half_open só um pedido (o "probe") passa: SET NX com TTL.
--
-- KEYS: 1 hash do circuito | 2 chave do probe
-- ARGV: 1 now_ms | 2 probe_ttl_ms
-- Devolve: 1 pode chamar | 0 saltar este hop

local now = tonumber(ARGV[1])
local state = redis.call('HGET', KEYS[1], 'state') or 'closed'

if state == 'closed' then
  return 1
end

if state == 'open' then
  local opened_until = tonumber(redis.call('HGET', KEYS[1], 'opened_until') or '0')
  if now < opened_until then
    return 0
  end
  redis.call('HSET', KEYS[1], 'state', 'half_open')
end

-- half_open: exactamente um probe de cada vez.
if redis.call('SET', KEYS[2], '1', 'NX', 'PX', tonumber(ARGV[2])) then
  return 1
end
return 0
