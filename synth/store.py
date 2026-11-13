import json
import sqlite3
import uuid
from collections import Counter


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY,source TEXT,status TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,qid TEXT,status TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS errors(kind TEXT);
            CREATE TABLE IF NOT EXISTS retrievals(id INTEGER PRIMARY KEY,qid TEXT);
        ''')
        if not self.meta('run_id'): self.set_meta('run_id', uuid.uuid4().hex)
        with self.db:
            self.db.execute("UPDATE calls SET status='uncertain' WHERE status='pending'")

    def meta(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_meta(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, dumps(value)))

    def set_upload(self, receipt, pending):
        with self.db:
            for key,value in (('upload',receipt),('upload_pending',pending)):
                self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(key,dumps(value)))

    def get(self, qid):
        row = self.db.execute('SELECT payload FROM questions WHERE id=?', (qid,)).fetchone()
        return json.loads(row[0]) if row else None

    def _put(self, task):
        self.db.execute('INSERT OR REPLACE INTO questions VALUES (?,?,?,?)',
                        (task['id'], task['source'], task['status'], dumps(task)))

    def save(self, task):
        with self.db: self._put(task)

    def begin_call(self, qid, request, logical_id):
        call_id = uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO calls VALUES (?,?,?,?)',
                            (call_id, qid, 'pending', dumps({'request': request, 'logical_id': logical_id})))
        return call_id

    def finish_call(self, call_id, status, payload, task=None):
        with self.db:
            self.db.execute('UPDATE calls SET status=?,payload=? WHERE id=?',
                            (status, dumps(payload), call_id))
            if task is not None: self._put(task)

    def retrieval(self, task):
        with self.db:
            self._put(task)
            self.db.execute('INSERT INTO retrievals(qid) VALUES (?)', (task['id'],))

    def error(self, kind):
        with self.db: self.db.execute('INSERT INTO errors VALUES (?)', (kind,))

    def accepted(self):
        return self.db.execute("SELECT COUNT(*) FROM questions WHERE status='accepted'").fetchone()[0]

    def stats(self, reason, upload):
        by_source = {}
        for row in self.db.execute('SELECT source,status,COUNT(*) AS n FROM questions GROUP BY source,status'):
            by_source.setdefault(row['source'], {'accepted': 0, 'rejected': 0, 'in_progress': 0})[row['status']] = row['n']
        statuses = Counter(dict(self.db.execute('SELECT status,COUNT(*) FROM questions GROUP BY status')))
        usage = Counter()
        unknown_usage = 0
        for row in self.db.execute("SELECT payload FROM calls WHERE status='succeeded'"):
            u = json.loads(row[0]).get('response', {}).get('usage')
            if isinstance(u, dict):
                for k in ('prompt_tokens', 'completion_tokens'):
                    if isinstance(u.get(k), int): usage[k] += u[k]
            else: unknown_usage += 1
        return dict(processed=statuses['accepted'] + statuses['rejected'], accepted=statuses['accepted'],
                    rejected=statuses['rejected'], in_progress=statuses['in_progress'], by_source=by_source,
                    api_calls=self.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0],
                    input_tokens=usage['prompt_tokens'], output_tokens=usage['completion_tokens'],
                    responses_without_usage=unknown_usage,
                    uncertain_requests=self.db.execute("SELECT COUNT(*) FROM calls WHERE status='uncertain'").fetchone()[0],
                    retrievals=self.db.execute('SELECT COUNT(*) FROM retrievals').fetchone()[0],
                    upload_attempts=self.meta('upload_attempts_total') or 0,
                    errors=dict(self.db.execute('SELECT kind,COUNT(*) FROM errors GROUP BY kind')),
                    stop_reason=reason, upload=upload, run_id=self.meta('run_id'))

    def close(self): self.db.close()
