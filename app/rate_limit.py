"""Скользящее окно в Redis: не больше N запросов за окно на один ключ."""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis import Redis

# Атомарно: почистить окно → посчитать → либо отказать, либо записать хит.
_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1])
local n = redis.call('ZCARD', KEYS[1])
if n >= tonumber(ARGV[2]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry = 0
  if oldest[2] then
    retry = math.ceil(tonumber(oldest[2]) + tonumber(ARGV[4]) - tonumber(ARGV[3]))
    if retry < 1 then retry = 1 end
  else
    retry = tonumber(ARGV[4])
  end
  return {0, n, retry}
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[3])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]) + 5)
return {1, n + 1, 0}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    used: int
    remaining: int
    retry_after: int
    limit: int
    window_sec: int


class RateLimiter:
    """Лимит на api_key.id, не на IP: ключ можно унести на другую машину."""

    def __init__(self, redis: Redis, *, limit: int, window_sec: int) -> None:
        self.redis = redis
        self.limit = limit
        self.window_sec = window_sec
        self._script = redis.register_script(_LUA)

    def hit(self, api_key_id: int) -> RateLimitResult:
        now = time.time()
        cutoff = now - self.window_sec
        allowed, used, retry = self._script(
            keys=[f"rl:{api_key_id}"],
            args=[cutoff, self.limit, now, self.window_sec],
        )
        used_i = int(used)
        allowed_b = bool(int(allowed))
        remaining = max(0, self.limit - used_i) if allowed_b else 0
        return RateLimitResult(
            allowed=allowed_b,
            used=used_i,
            remaining=remaining,
            retry_after=int(retry),
            limit=self.limit,
            window_sec=self.window_sec,
        )

    def peek(self, api_key_id: int) -> RateLimitResult:
        """Сколько уже сожгли в текущем окне — для плашки в UI, без записи хита."""
        now = time.time()
        key = f"rl:{api_key_id}"
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - self.window_sec)
        pipe.zcard(key)
        _, used = pipe.execute()
        used_i = int(used or 0)
        remaining = max(0, self.limit - used_i)
        return RateLimitResult(
            allowed=used_i < self.limit,
            used=used_i,
            remaining=remaining,
            retry_after=0,
            limit=self.limit,
            window_sec=self.window_sec,
        )
