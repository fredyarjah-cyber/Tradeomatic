import io
import json
from scripts.probe_provider import probe


def transport(data, calls):
    def open_response(request, timeout):
        calls.append(request)
        return io.BytesIO(json.dumps(data).encode())
    return open_response


def test_missing_key_never_requests():
    assert probe('', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))['requests'] == 0


def test_success_makes_one_request_without_returning_key():
    calls = []
    data = {'values': [{'datetime': '2026-11-17 00:00:00', 'open': '1.1', 'high': '1.2', 'low': '1.0', 'close': '1.15'}]}
    result = probe('private-test-value', transport(data, calls))
    assert result['ok'] and len(calls) == 1
    assert 'private-test-value' not in json.dumps(result)


def test_provider_message_cannot_expose_secret():
    result = probe('secret', transport({'status': 'error', 'code': 429, 'message': 'secret'}, []))
    assert result['provider_code'] == 429
    assert 'secret' not in json.dumps(result)


def test_transport_exception_cannot_expose_secret():
    def fail(*args, **kwargs):
        raise RuntimeError('https://example.com/?apikey=secret')
    assert 'secret' not in json.dumps(probe('secret', fail))


def test_invalid_candles_rejected():
    data = {'values': [{'datetime': 'today', 'open': 'nan', 'high': '2', 'low': '1', 'close': '1.5'}]}
    assert probe('secret', transport(data, []))['result'] == 'INVALID_CANDLES'
