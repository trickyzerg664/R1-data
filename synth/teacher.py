import json
import http.client
import os
import socket
import time
import urllib.error
import urllib.request

from .errors import (ConfigurationError, QuotaExhausted, ServiceUnavailable,
                     classify, retry_delay)


class Teacher:
    def __init__(self, cfg, store, opener=None, sleep=time.sleep):
        self.cfg, self.store, self.sleep = cfg, store, sleep
        self.open = opener or urllib.request.urlopen
        self.base = os.environ.get('API_BASE_URL', '').rstrip('/')
        self.key = os.environ.get('API_KEY', '')
        if not self.base.startswith(('https://', 'http://')) or not self.key or not cfg['model']:
            raise ConfigurationError('需要 API_BASE_URL、API_KEY，以及维护者预设 teacher.model。')

    def complete(self, task, commit):
        messages = task['messages']
        payload = dict(model=self.cfg['model'], messages=messages, temperature=self.cfg['temperature'],
                       max_tokens=self.cfg['max_tokens'], stream=False)
        if self.cfg.get('provider') == 'deepseek':
            # Keep explicit Search-R1 <think> tags in actual content; no reconstructed hidden reasoning.
            payload['thinking'] = self.cfg.get('thinking', {'type': 'disabled'})
        logical_id = f"{self.store.meta('run_id')}:{task['id']}:{task['attempt']}:{task['turn']}"
        for attempt in range(self.cfg['retries'] + 1):
            call_id = self.store.begin_call(task['id'], payload, logical_id)
            headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key}
            if self.cfg.get('idempotency_header'):
                headers[self.cfg['idempotency_header']] = logical_id
            request = urllib.request.Request(self.base + '/chat/completions',
                                             data=json.dumps(payload).encode(), headers=headers)
            try:
                with self.open(request, timeout=self.cfg['timeout']) as r:
                    raw = r.read().decode('utf-8')
                try: response = json.loads(raw)
                except ValueError:
                    self.store.finish_call(call_id, 'uncertain', {'request': payload, 'raw': raw})
                    raise ServiceUnavailable('API 返回非 JSON，结果和用量可能不确定。')
                commit(response, payload, call_id)
                return
            except urllib.error.HTTPError as exc:
                body = exc.read().decode('utf-8', errors='replace')
                kind = classify(exc.code, body, self.cfg.get('provider'))
                # No authentication headers or keys are stored in the journal.
                self.store.finish_call(call_id, 'failed', {'http_status': exc.code, 'kind': kind})
                self.store.error(kind if kind != 'recoverable' else f'api_http_{exc.code}')
                if kind == 'quota_exhausted': raise QuotaExhausted('服务商明确返回额度或余额不足。')
                if kind == 'configuration_error': raise ConfigurationError(f'API 永久错误 HTTP {exc.code}，请检查密钥、模型及接口。')
                delay = retry_delay(dict(exc.headers), attempt, self.cfg['backoff_base'], self.cfg['backoff_cap'])
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError, http.client.HTTPException):
                self.store.finish_call(call_id, 'uncertain', {'request': payload, 'logical_id': logical_id})
                self.store.error('api_network_uncertain')
                delay = retry_delay({}, attempt, self.cfg['backoff_base'], self.cfg['backoff_cap'])
            if attempt >= self.cfg['retries']:
                raise ServiceUnavailable('API 临时错误重试耗尽；保留当前轮次，下次运行恢复。')
            self.sleep(delay)


class MockTeacher:
    def __init__(self, store): self.store = store

    def complete(self, task, commit):
        # Synthetic fixtures only; never substitutes for real API in live mode.
        text = '<think>Look up the fixture.</think><search>mock fixture</search>' if task['turn'] == 0 else '<think>Use the fixture.</think><answer>fixture answer</answer>'
        response = {'choices': [{'message': {'role': 'assistant', 'content': text}}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5}, 'mock': True}
        request = {'messages': task['messages'], 'mock': True}
        call_id = self.store.begin_call(task['id'], request, 'mock')
        commit(response, request, call_id)
