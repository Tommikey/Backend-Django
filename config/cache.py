"""The Redis cache, made to fail open: if Redis can't be reached, reads miss and writes are
dropped (logged) instead of failing the request. The cache holds rate-limit counters, so an
outage pauses rate limiting rather than taking sign-in down with it."""

import functools
import logging

from django.core.cache.backends.redis import RedisCache
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# method -> what it returns when Redis is unreachable
FALLBACKS = {
    "add": False,
    "get": None,  # replaced by the caller's default
    "set": None,
    "touch": False,
    "delete": False,
    "get_many": {},
    "has_key": False,
    "set_many": [],
    "delete_many": None,
}


def _forgiving(name, fallback):
    method = getattr(RedisCache, name)

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except RedisError:
            logger.warning("cache unavailable: %s skipped", name, exc_info=True)
            if name == "get":
                return kwargs.get("default", args[1] if len(args) > 1 else None)
            return type(fallback)() if isinstance(fallback, dict | list) else fallback

    return wrapper


class ForgivingRedisCache(RedisCache):
    pass


for _name, _fallback in FALLBACKS.items():
    setattr(ForgivingRedisCache, _name, _forgiving(_name, _fallback))
