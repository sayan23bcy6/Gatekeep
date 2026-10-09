--[[
Sliding Window Log rate limiter — executed atomically in Redis.

Uses a sorted set scored by microsecond timestamp.
Each member is unique: "<timestamp_us>:<random_suffix>" to allow
multiple requests at the same microsecond.

KEYS[1]  = sorted-set key  e.g. "rl:{client_id}:{route}:sw"
ARGV[1]  = limit           (integer, max requests per window)
ARGV[2]  = window_seconds  (float)
ARGV[3]  = ttl             (integer, seconds before idle key expires)

Returns an array: { allowed, remaining, retry_after_ms, reset_after_ms }
--]]

local key            = KEYS[1]
local limit          = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local ttl            = tonumber(ARGV[3])

-- Redis server time
local t         = redis.call('TIME')
local now_us    = tonumber(t[1]) * 1000000 + tonumber(t[2])
local cutoff_us = now_us - math.floor(window_seconds * 1000000)

-- Remove entries outside the window
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff_us)

local count = redis.call('ZCARD', key)

local allowed, remaining, retry_after_ms, reset_after_ms

if count < limit then
    -- Unique member: timestamp + redis random (TIME microseconds always unique enough
    -- within single Lua call, but add count as suffix for safety)
    local member = tostring(now_us) .. ':' .. tostring(count)
    redis.call('ZADD', key, now_us, member)
    redis.call('EXPIRE', key, ttl)
    remaining    = limit - count - 1
    allowed      = 1
    retry_after_ms = 0
    -- Window resets when the oldest entry (after insertion) falls out
    local oldest_score = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    if oldest_score and #oldest_score >= 2 then
        local oldest_us = tonumber(oldest_score[2])
        reset_after_ms = math.ceil(((oldest_us + math.floor(window_seconds * 1000000)) - now_us) / 1000)
        if reset_after_ms < 0 then reset_after_ms = 0 end
    else
        reset_after_ms = math.ceil(window_seconds * 1000)
    end
else
    allowed      = 0
    remaining    = 0
    -- Retry after the oldest entry leaves the window
    local oldest_score = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    if oldest_score and #oldest_score >= 2 then
        local oldest_us = tonumber(oldest_score[2])
        retry_after_ms  = math.ceil(((oldest_us + math.floor(window_seconds * 1000000)) - now_us) / 1000)
        if retry_after_ms < 0 then retry_after_ms = 0 end
        reset_after_ms  = retry_after_ms
    else
        retry_after_ms  = math.ceil(window_seconds * 1000)
        reset_after_ms  = retry_after_ms
    end
    redis.call('EXPIRE', key, ttl)
end

return { allowed, remaining, retry_after_ms, reset_after_ms }
