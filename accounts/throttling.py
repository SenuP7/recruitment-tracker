"""Attempt throttling for sign-in and password reset.

Django has no brute-force protection of its own: without this, an attacker
can try passwords against a known username as fast as the network allows,
and the public password-reset form can be used to send unlimited email at
our expense.

Counters live in the cache, which is a database table in production
(`manage.py createcachetable`), so limits hold across processes and across
instances behind the load balancer. A cache that loses its contents fails
open -- it lets people in rather than locking everyone out, which is the
right way round for a recruitment tool.
"""

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Generous enough that a person mistyping a password a few times is fine.
LOGIN_MAX_PER_USERNAME = 6
LOGIN_MAX_PER_IP = 20
LOGIN_WINDOW_SECONDS = 15 * 60

RESET_MAX_PER_IP = 5
RESET_WINDOW_SECONDS = 60 * 60

LOCKED_OUT_MESSAGE = (
    "Too many attempts. Wait 15 minutes and try again, or reset your password."
)
RESET_THROTTLED_MESSAGE = (
    "That's a lot of reset requests. Please wait an hour, or email us for help."
)


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or "unknown"


def _count(key):
    """Fails open. If the cache is unreachable -- the table hasn't been
    created in a new environment, say -- throttling stops working, but people
    can still sign in. A lockout that locks everyone out is worse than no
    lockout."""
    try:
        return cache.get(key) or 0
    except Exception as error:
        logger.error("Throttle cache unavailable (%s); allowing the request", error)
        return 0


def _record(key, window):
    """Counts one attempt. `add` then `incr` so the window starts at the first
    attempt and isn't extended by later ones."""
    try:
        if cache.add(key, 1, window):
            return 1
        return cache.incr(key)
    except ValueError:
        # The entry expired between add and incr.
        cache.set(key, 1, window)
        return 1
    except Exception as error:
        logger.error("Throttle cache unavailable (%s); attempt not counted", error)
        return 0


def is_locked_out(request, username=""):
    ip_key = f"login-attempts:ip:{client_ip(request)}"
    if _count(ip_key) >= LOGIN_MAX_PER_IP:
        return True
    if username:
        return _count(f"login-attempts:user:{username.lower()}") >= LOGIN_MAX_PER_USERNAME
    return False


def record_failed_login(request, username=""):
    ip = client_ip(request)
    _record(f"login-attempts:ip:{ip}", LOGIN_WINDOW_SECONDS)
    if username:
        _record(f"login-attempts:user:{username.lower()}", LOGIN_WINDOW_SECONDS)
    logger.info("Failed sign-in for %r from %s", username, ip)


def clear_login_attempts(request, username=""):
    try:
        cache.delete(f"login-attempts:ip:{client_ip(request)}")
        if username:
            cache.delete(f"login-attempts:user:{username.lower()}")
    except Exception as error:
        logger.error("Throttle cache unavailable (%s); counters not cleared", error)


def reset_requests_exhausted(request):
    return _count(f"reset-requests:{client_ip(request)}") >= RESET_MAX_PER_IP


def record_reset_request(request):
    _record(f"reset-requests:{client_ip(request)}", RESET_WINDOW_SECONDS)
