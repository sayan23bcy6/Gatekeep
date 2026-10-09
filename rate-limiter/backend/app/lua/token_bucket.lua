--[[
Token Bucket rate limiter — executed atomically in Redis.

KEYS[1]  = bucket key  e.g. "rl:{client_id}:{route}"
ARGV[1]  = capacity    (integer, maximum tokens)
ARGV[2]  = refill_rate (float, tokens per second)
ARGV[3]  = ttl         (integer, seconds before idle key expires)

Returns an array: { allowed, remaining, retry_after_ms, reset_after_ms }
  allowed = 1 or 0
  remaining = integer tokens left after this call
  retry_after_ms = milliseconds until 1 token is available (0 if allowed)
  reset_after_ms = milliseconds until bucket is full
--]]

local key          = KEYS[1]
local capacity     = tonumber(ARGV[1])
local refill_rate  = tonumber(ARGV[2])   -- tokens / second
local ttl          = tonumber(ARGV[3])

-- Use Redis server time to avoid client clock skew
local t            = redis.call('TIME')  -- {seconds, microseconds}
local now_us       = tonumber(t[1]) * 1000000 + tonumber(t[2])  -- microseconds

local bucket       = redis.call('HMGET', key, 'tokens', 'ts')
local tokens
local last_ts_us

if bucket[1] == false then
    -- First request: start full
    tokens      = capacity
    last_ts_us  = now_us
else
    tokens      = tonumber(bucket[1])
    last_ts_us  = tonumber(bucket[2])
end

-- Refill based on elapsed time (microseconds → seconds)
local elapsed_s = (now_us - last_ts_us) / 1000000.0
if elapsed_s < 0 then elapsed_s = 0 end

tokens = math.min(capacity, tokens + elapsed_s * refill_rate)

local allowed, remaining, retry_after_ms, reset_after_ms

if tokens >= 1.0 then
    tokens       = tokens - 1.0
    remaining    = math.floor(tokens)
    allowed      = 1
    retry_after_ms = 0
    -- ms until full
    local missing = capacity - tokens
    reset_after_ms = math.ceil(missing / refill_rate * 1000)
else
    allowed      = 0
    remaining    = 0
    -- ms until 1 token arrives
    local deficit = 1.0 - tokens
    retry_after_ms  = math.ceil(deficit / refill_rate * 1000)
    local missing   = capacity - tokens
    reset_after_ms  = math.ceil(missing / refill_rate * 1000)
end

-- Persist state
redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now_us))
redis.call('EXPIRE', key, ttl)

return { allowed, remaining, retry_after_ms, reset_after_ms }
