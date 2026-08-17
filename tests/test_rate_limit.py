from fakeredis import FakeRedis

from app.rate_limit import RateLimiter


def test_fifth_allowed_sixth_denied():
    redis = FakeRedis(decode_responses=True)
    limiter = RateLimiter(redis, limit=5, window_sec=60)

    last = None
    for _ in range(5):
        last = limiter.hit(1)
        assert last.allowed

    denied = limiter.hit(1)
    assert not denied.allowed
    assert denied.remaining == 0
    assert denied.retry_after >= 1
    assert last is not None
    assert last.remaining == 0


def test_peek_does_not_consume():
    redis = FakeRedis(decode_responses=True)
    limiter = RateLimiter(redis, limit=5, window_sec=60)
    limiter.hit(7)
    peek1 = limiter.peek(7)
    peek2 = limiter.peek(7)
    assert peek1.used == peek2.used == 1
