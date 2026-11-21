-- Reserva atómica de orçamento para a chave E para a equipa. Ou ambas, ou nenhuma.
-- Invariante por âmbito: spent + reserved + estimate <= budget (quando budget >= 0).
--
-- KEYS: 1 key_spent | 2 key_reserved | 3 team_spent | 4 team_reserved | 5 resv_key | 6 pending_zset
-- ARGV: 1 key_budget_micro | 2 team_budget_micro (-1 = sem limite) | 3 estimate_micro
--       4 expires_at_ms | 5 reservation_id | 6 payload_json
-- Devolve: 0 ok | 1 orçamento da chave excedido | 2 orçamento da equipa excedido

local key_budget = tonumber(ARGV[1])
local team_budget = tonumber(ARGV[2])
local estimate = tonumber(ARGV[3])

if key_budget >= 0 then
  local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
  local reserved = tonumber(redis.call('GET', KEYS[2]) or '0')
  if spent + reserved + estimate > key_budget then
    return 1
  end
end

if team_budget >= 0 then
  local spent = tonumber(redis.call('GET', KEYS[3]) or '0')
  local reserved = tonumber(redis.call('GET', KEYS[4]) or '0')
  if spent + reserved + estimate > team_budget then
    return 2
  end
end

redis.call('INCRBY', KEYS[2], estimate)
redis.call('INCRBY', KEYS[4], estimate)
redis.call('SET', KEYS[5], ARGV[6])
redis.call('ZADD', KEYS[6], tonumber(ARGV[4]), ARGV[5])
return 0
