import email.utils
import json
import random
import re
import time
from datetime import datetime, timezone


class StopRun(Exception):
    reason = 'global_error'


class QuotaExhausted(StopRun):
    reason = 'quota_exhausted'


class ConfigurationError(StopRun):
    reason = 'configuration_error'


class ServiceUnavailable(StopRun):
    reason = 'api_unavailable'


class RetrieverUnavailable(StopRun):
    reason = 'retriever_unavailable'


class QuestionError(Exception):
    pass


def classify(status, body, provider=None):
    """Explicit quota evidence wins; a bare 429 is only a rate limit."""
    # DeepSeek documents HTTP 402 as Insufficient Balance, even without a JSON body.
    if provider == 'deepseek' and status == 402: return 'quota_exhausted'
    try:
        obj = json.loads(body)
        err = obj.get('error', obj)
        if not isinstance(err, dict): err = {'message': str(err)}
    except (ValueError, AttributeError):
        err = {'message': str(body)}
    code = str(err.get('code', '')).lower()
    text = ' '.join(str(err.get(k, '')) for k in ('code', 'type', 'message')).lower()
    quota_codes = {'insufficient_quota', 'insufficient_balance', 'quota_exhausted',
                   'balance_not_enough', 'credit_balance_too_low', 'out_of_credits'}
    phrases = ('insufficient balance', 'insufficient quota', 'credit balance is too low',
               'quota exhausted', 'out of credits', '余额不足', '额度耗尽', '配额耗尽')
    if code in quota_codes or any(p in text for p in phrases): return 'quota_exhausted'
    if status in (401, 403, 404, 405, 400, 422): return 'configuration_error'
    if status in (408, 409, 425, 429) or 500 <= status <= 599: return 'recoverable'
    return 'configuration_error'


def retry_delay(headers, attempt, base=2, cap=60):
    raw = next((v for k, v in headers.items() if k.lower() == 'retry-after'), None)
    if raw is not None:
        try: return max(0.0, float(raw))
        except (ValueError, TypeError):
            try:
                dt = email.utils.parsedate_to_datetime(raw)
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError): pass
    return random.uniform(0, min(cap, base * 2 ** attempt))


def safe_message(text, secrets=()):
    text = str(text)
    for value in secrets:
        if value: text = text.replace(value, '[REDACTED]')
    return re.sub(r'(?i)bearer\s+\S+', 'Bearer [REDACTED]', text)[:400]
