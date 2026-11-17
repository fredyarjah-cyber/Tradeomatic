"""One-request Twelve Data credential test; never starts discovery or orders."""
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request


def probe(key, opener=urllib.request.urlopen):
    if not key or not key.strip():
        return {'ok': False, 'result': 'KEY_NOT_CONFIGURED', 'requests': 0}
    query = urllib.parse.urlencode({'symbol': 'EUR/USD', 'interval': '1h',
                                   'outputsize': 2, 'timezone': 'UTC', 'apikey': key.strip()})
    request = urllib.request.Request('https://api.twelvedata.com/time_series?' + query)
    try:
        with opener(request, timeout=20) as response:
            data = json.loads(response.read(65536))
    except urllib.error.HTTPError as error:
        return {'ok': False, 'result': 'HTTP_ERROR', 'http_status': error.code, 'requests': 1}
    except Exception:
        # Transport exceptions may contain the URL and credential. Never print them.
        return {'ok': False, 'result': 'CONNECTION_OR_RESPONSE_ERROR', 'requests': 1}
    if not isinstance(data, dict):
        return {'ok': False, 'result': 'INVALID_RESPONSE', 'requests': 1}
    if data.get('status') == 'error':
        code = data.get('code')
        return {'ok': False, 'result': 'PROVIDER_REJECTED',
                'provider_code': code if isinstance(code, int) else None, 'requests': 1}
    try:
        values = data['values']
        if not isinstance(values, list) or not values:
            raise ValueError()
        for bar in values:
            o, h, l, c = (float(bar[k]) for k in ('open', 'high', 'low', 'close'))
            if not all(math.isfinite(n) for n in (o, h, l, c)) or not 0 < l <= min(o, c) <= max(o, c) <= h:
                raise ValueError()
            if not isinstance(bar['datetime'], str):
                raise ValueError()
    except (KeyError, TypeError, ValueError):
        return {'ok': False, 'result': 'INVALID_CANDLES', 'requests': 1}
    return {'ok': True, 'result': 'CANDLES_RECEIVED', 'symbol': 'EUR/USD',
            'interval': '1h', 'candles_received': len(values),
            'latest_candle_time': values[0]['datetime'], 'requests': 1,
            'note': 'Credential test only; data entitlement and freshness are not certified. Scanner and orders unchanged.'}


if __name__ == '__main__':
    result = probe(os.getenv('TWELVEDATA_API_KEY', ''))
    print(json.dumps(result))
    raise SystemExit(0 if result['ok'] else 1)
