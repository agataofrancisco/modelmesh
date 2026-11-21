-- Reconciliação: troca a reserva pelo custo real (real = 0 para libertar em falha).
-- Idempotente: se a reserva já não existe (reconciliada, libertada ou expirada), não faz nada.
--
-- KEYS: 1 key_spent | 2 key_reserved | 3 team_spent | 4 team_reserved | 5 resv_key | 6 pending_zset
-- ARGV: 1 estimate_micro | 2 real_micro | 3 reservation_id
-- Devolve: 1 aplicado | 0 já não existia

if redis.call('EXISTS', KEYS[5]) == 0 then
  return 0
end

local estimate = tonumber(ARGV[1])
local real = tonumber(ARGV[2])

redis.call('DEL', KEYS[5])
redis.call('ZREM', KEYS[6], ARGV[3])

redis.call('DECRBY', KEYS[2], estimate)
redis.call('INCRBY', KEYS[1], real)
redis.call('DECRBY', KEYS[4], estimate)
redis.call('INCRBY', KEYS[3], real)
return 1
