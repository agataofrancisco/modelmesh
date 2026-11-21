-- Liberta concorrência. Nunca deixa o contador negativo (protege contra TTL expirado).
-- KEYS: contadores de concorrência a libertar (só os âmbitos com limite > 0).
for _, key in ipairs(KEYS) do
  local value = redis.call('DECR', key)
  if value < 0 then
    redis.call('SET', key, 0)
  end
end
return #KEYS
