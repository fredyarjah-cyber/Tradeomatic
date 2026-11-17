"""Persistent request accounting shared by API and scanner processes."""
import os
from datetime import datetime, timezone
from . import db


class ProviderLimit(RuntimeError):
    pass


def limits():
    try:
        daily = int(os.getenv('PROVIDER_DAILY_CREDITS', '700'))
        minute = int(os.getenv('PROVIDER_MINUTE_CREDITS', '6'))
        if not 1 <= daily <= 800 or not 1 <= minute <= 8:
            raise ValueError()
        return daily, minute
    except ValueError:
        raise ProviderLimit('Invalid provider credit limits; requests blocked') from None


def reserve(now):
    """Count before sending. Failed requests count; no automatic retries."""
    daily, minute = limits()
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    with db.atomic() as tx:
        record = tx.get('provider_usage', 'twelvedata', {})
        recent = [t for t in record.get('recent', []) if t > now - 60]
        used = record.get('used', 0) if record.get('day') == day else 0
        if used >= daily:
            raise ProviderLimit('Daily market-data budget reached; requests paused until next UTC day')
        if len(recent) >= minute:
            raise ProviderLimit('Market-data rate limit reached; request deferred')
        tx.put('provider_usage', 'twelvedata', {'day': day, 'used': used + 1, 'recent': recent + [now]})


def status(now):
    daily, minute = limits()
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    record = db.get('provider_usage', 'twelvedata', {})
    used = record.get('used', 0) if record.get('day') == day else 0
    return {'day_utc': day, 'daily_limit': daily, 'credits_reserved': used,
            'credits_remaining': max(0, daily - used), 'minute_limit': minute,
            'scope': 'This installation only; other apps and manual probes are not counted.'}
