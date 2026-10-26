"""SQLite 持久层：任务计划与事件的唯一事实源，跨进程共享。

并发控制：所有写路径走 BEGIN IMMEDIATE，同一时刻仅一个写入者，
两个进程的交错提交被串行化，同工位时间片不会重叠。
"""
import json
import sqlite3
from contextlib import contextmanager

SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(
    job_id TEXT PRIMARY KEY, station_id TEXT NOT NULL,
    ready_s INTEGER NOT NULL, start_s INTEGER NOT NULL, end_s INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(
    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
    event TEXT NOT NULL, detail TEXT NOT NULL);
'''


class PlanStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.executescript(SCHEMA)

    def bind_case(self, signature):
        with self.transaction():
            row = self.db.execute("SELECT value FROM meta WHERE key='case_signature'").fetchone()
            if row is None:
                self.db.execute("INSERT INTO meta VALUES('case_signature',?)", (signature,))
            elif row[0] != signature:
                raise ValueError('case changed: use a different database for a different experiment')

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        self.db.execute('COMMIT')

    def get_job(self, job_id):
        row = self.db.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
        return dict(row) if row else None

    def insert_job(self, job_id, station_id, ready_s, start_s, end_s):
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',
                        (job_id, station_id, ready_s, start_s, end_s))

    def station_last_end(self, station_id):
        row = self.db.execute('SELECT MAX(end_s) FROM jobs WHERE station_id=?', (station_id,)).fetchone()
        return row[0] or 0

    def append_event(self, job_id, event, detail):
        cursor = self.db.execute('INSERT INTO events(job_id,event,detail) VALUES(?,?,?)',
                                 (job_id, event, json_detail(detail)))
        return cursor.lastrowid

    def all_jobs(self):
        return [dict(r) for r in self.db.execute(
            'SELECT * FROM jobs ORDER BY start_s,station_id,job_id')]

    def all_events(self):
        return [as_event(r) for r in self.db.execute('SELECT * FROM events ORDER BY seq')]

    def events_of(self, job_id):
        return [as_event(r) for r in self.db.execute(
            'SELECT * FROM events WHERE job_id=? ORDER BY seq', (job_id,))]

    def close(self):
        self.db.close()


def json_detail(detail):
    return json.dumps(detail, sort_keys=True)


def as_event(row):
    event = dict(row)
    event['detail'] = json.loads(event['detail'])
    return event
