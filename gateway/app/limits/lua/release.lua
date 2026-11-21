-- Remove only the request's concurrency lease from each enabled scope.
-- KEYS: concurrency lease sorted sets; ARGV[1]: unique lease member.
for _, key in ipairs(KEYS) do
  redis.call('ZREM', key, ARGV[1])
end
return #KEYS
