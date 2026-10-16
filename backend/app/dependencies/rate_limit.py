"""Redis 限流依赖。

AI 接口是成本大头，必须有简单的限流。这里用 Redis 的 INCR + EXPIRE
实现“每个用户每分钟最多 N 次”。没有配置 Redis 时自动放行，不影响本地开发。
"""

from fastapi import Depends, HTTPException, status

from app.config import settings
from app.dependencies.auth import get_current_user
from app.models.user import User

_redis = None
_redis_attempted = False


def get_redis():
    """返回 Redis 客户端；未配置或不可用返回 None。"""
    global _redis, _redis_attempted
    if _redis_attempted:
        return _redis
    _redis_attempted = True
    if not settings.REDIS_URL:
        return None
    try:
        import redis

        _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        _redis = None
    return _redis


def ai_rate_limiter(
    current_user: User = Depends(get_current_user),
):
    """AI 接口限流：每分钟 20 次。"""
    redis_client = get_redis()
    if redis_client is None:
        # 没有 Redis 就不限流，保证本地零配置可用。
        yield
        return

    key = f"ai:ratelimit:{current_user.id}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, 60)
        if count > 20:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="请求过于频繁，请稍后再试",
            )
    except HTTPException:
        raise
    except Exception:
        # Redis 抖动时降级为放行，不阻塞核心功能。
        pass
    yield
