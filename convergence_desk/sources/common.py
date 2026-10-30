"""Bounded stdlib HTTP, retry/circuit protection and privacy-safe checkpoints."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from convergence_desk.core.resilience import CircuitBreaker, CheckpointStore, RetryableError, retry
from convergence_desk.core.trail import canonical_json, content_hash

UA = 'ConvergenceDesk/0.1 (open-source practice-only market research; public read-only feeds; no credentials)'
MAX_BODY = 2_000_000


def iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


@dataclass
class Batch:
    items: tuple
    provenance: tuple
    features: dict = None
    metadata: dict = None


class Client:
    def __init__(self, checkpoint, *, kill=None, recordings=None, record_to=None, pace=.2):
        self.store = CheckpointStore(checkpoint)
        self.breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        self.kill = kill or os.environ.get('CONVERGENCE_KILL_SOURCE', '')
        self.recordings = Path(recordings) if recordings else None
        self.record_to = Path(record_to) if record_to else None
        self.pace = 0 if recordings else pace
        self.requests = []
        self.deferred_until = {}

    def fetch(self, source, endpoint, parser, payload=None):
        """Commit only parser-sanitized data; an interrupted run resumes requests."""
        key = content_hash({'source': source, 'endpoint': endpoint, 'payload': payload})
        if self.kill and (source == self.kill or source.startswith(self.kill + ':')):
            raise RuntimeError('deliberate chaos failure: ' + source)
        if time.monotonic() < self.deferred_until.get(source, 0):
            raise RuntimeError('source deferred until its Retry-After interval expires')
        entry = self.store.load()['sources'].get(key)
        if entry:
            return entry['state']

        def operation():
            time.sleep(self.pace)
            stamp = iso(datetime.now(timezone.utc))
            body = b''
            status = None
            headers = {}
            try:
                if self.recordings:
                    fixture = json.loads((self.recordings / (key + '.json')).read_text())
                    if fixture.get('recorded_test_fixture') is not True:
                        raise ValueError('not a recorded test fixture')
                    body = fixture['body'].encode()
                    status, headers, stamp = fixture['status'], fixture['headers'], fixture['fetch_time']
                    if status >= 400:
                        raise RetryableError(f'HTTP {status}', status, headers.get('Retry-After'))
                else:
                    data = json.dumps(payload).encode() if payload is not None else None
                    request = urllib.request.Request(endpoint, data=data, headers={
                        'User-Agent': UA, 'Accept': '*/*', 'Content-Type': 'application/json'})
                    try:
                        with urllib.request.urlopen(request, timeout=8) as response:
                            status = response.status
                            headers = dict(response.headers)
                            body = response.read(MAX_BODY + 1)
                    except urllib.error.HTTPError as error:
                        status = error.code
                        headers = dict(error.headers)
                        raise RetryableError(f'HTTP {status} from {endpoint}', status, headers.get('Retry-After')) from error
                    except (urllib.error.URLError, TimeoutError, OSError) as error:
                        raise RetryableError(f'{type(error).__name__}: {error}') from error
                if len(body) > MAX_BODY:
                    raise ValueError('response exceeds 2 MB cap')
                provenance = dict(source=source, endpoint=endpoint, fetch_time=stamp,
                                  http_status=status, response_sha256=sha(body))
                if payload is not None:
                    provenance['rpc_request'] = payload
                parsed = parser(body, provenance)
                if self.recordings and fixture.get('post_features'):
                    # Recorded fixtures erase publisher prose. The independently
                    # recorded extraction features preserve a meaningful E2E run.
                    rows = parsed if isinstance(parsed, list) else parsed.get('rows', [])
                    for row in rows:
                        saved = fixture['post_features'].get(row['uri'])
                        if saved:
                            row.update(saved)
                            row['provenance']['content_sha256'] = saved['content_sha256']
                self.requests.append(provenance)
                if self.record_to:
                    from .recording import save_recording
                    save_recording(self.record_to, key, source, endpoint, payload, body, status, headers, stamp, parsed)
                return parsed
            except Exception as error:
                self.requests.append(dict(source=source, endpoint=endpoint, fetch_time=stamp,
                                          http_status=status, error=str(error)[:300]))
                raise

        def wait_for_retry(seconds):
            if seconds > 15:
                # Respect long Retry-After values without blocking the entire
                # judge demo. No further request to this source is made early.
                self.deferred_until[source] = time.monotonic() + seconds
                raise RuntimeError(f'source deferred: Retry-After {seconds:g}s exceeds 15s demo wait budget')
            time.sleep(seconds)

        value = self.breaker.call(source, lambda: retry(operation, attempts=2, base_delay=.5,
                                                        max_delay=2, sleep=wait_for_retry))
        value = json.loads(canonical_json(value))
        # Parsers must return only safe JSON values, never raw article/post bodies.
        self.store.save(key, key, value)
        return value


def json_parser(body, provenance):
    value = json.loads(body)
    if isinstance(value, dict) and value.get('error'):
        raise ValueError('API error: ' + str(value['error'])[:240])
    return {'data': value, 'provenance': provenance}


def item_provenance(provenance, identity, value):
    return {**provenance, 'identity': identity, 'content_sha256': content_hash(value)}
