"""受理、查询与统计：平台契约的业务实现。

不变量：
- 每个新计划恰好对应一条 accepted 与一条 planned 事件；
- 每次有效重试或冲突恰好对应一条 duplicate 或 conflict 事件；
- 同一工位的计划区间互斥，由事务内的工位 MAX(end_s) 推进保证；
- 查询只读，不改变计划与事件；指标与事件来自同一持久记录。
"""
from collections import Counter

from backend.case_loader import TIME_LIMIT_S
from backend.errors import RequestError


class TaskService:
    def __init__(self, store, scheduler, stations):
        self.store = store
        self.scheduler = scheduler
        self.stations = stations

    def handle(self, request):
        if not isinstance(request, dict) or 'op' not in request:
            raise RequestError('invalid_request', 'request must be an object with op')
        op = request['op']
        if op == 'submit':
            return self.submit(request.get('job'))
        if op == 'get':
            return self.get(request.get('job_id'), request.get('at_s', 0))
        if op == 'report':
            return self.report(request.get('at_s', 0))
        raise RequestError('unknown_op', f'unsupported op: {op!r}')

    def submit(self, job):
        normalized = self._validate_job(job)
        with self.store.transaction():
            existing = self.store.get_job(normalized['job_id'])
            if existing is not None:
                return self._record_retry(existing, normalized)
            return self._plan_new(normalized)

    def get(self, job_id, at_s):
        at = _validate_at(at_s)
        if not isinstance(job_id, str) or not job_id:
            raise RequestError('invalid_request', 'job_id must be a nonempty string')
        row = self.store.get_job(job_id)
        if row is None:
            return {'status': 'not_found'}
        events = self.store.events_of(job_id)
        return {'status': 'ok', 'state': _state_at(row, at),
                'run': _run_of(row), 'wait': _wait_of(row, events), 'events': events}

    def report(self, at_s):
        at = _validate_at(at_s)
        runs = self.store.all_jobs()
        events = self.store.all_events()
        counts = Counter(event['event'] for event in events)
        metrics = {'at_s': at,
                   'planned_count': len(runs),
                   'simulated_completed_count': sum(1 for row in runs if row['end_s'] <= at),
                   'event_counts': dict(counts)}
        return {'status': 'ok', 'record_kind': 'virtual_plan_and_replay',
                'runs': [_run_of(row) for row in runs],
                'events': events, 'metrics': metrics}

    def _record_retry(self, existing, normalized):
        same = (existing['station_id'], existing['ready_s']) == (normalized['station_id'], normalized['ready_s'])
        kind = 'duplicate' if same else 'conflict'
        reason = 'identical_payload' if same else 'payload_mismatch'
        self.store.append_event(existing['job_id'], kind, {'reason': reason})
        return {'status': kind, 'run': _run_of(existing)}

    def _plan_new(self, job):
        cycle = self.stations[job['station_id']]['cycle_s']
        start, previous_end = self.scheduler.earliest(job['ready_s'], job['station_id'])
        end = start + cycle
        if end > TIME_LIMIT_S:
            raise RequestError('plan_exceeds_time_limit', f'plan end {end} exceeds {TIME_LIMIT_S}')
        self.store.insert_job(job['job_id'], job['station_id'], job['ready_s'], start, end)
        self.store.append_event(job['job_id'], 'accepted', {'payload': dict(job)})
        planned = {'start_s': start, 'end_s': end, 'wait_s': start - job['ready_s'],
                   'reason': 'station_idle' if previous_end <= job['ready_s'] else 'station_busy',
                   'station_free_at': previous_end}
        self.store.append_event(job['job_id'], 'planned', planned)
        run = {'job_id': job['job_id'], 'station_id': job['station_id'],
               'ready_s': job['ready_s'], 'start_s': start, 'end_s': end}
        return {'status': 'accepted', 'run': run}

    def _validate_job(self, job):
        if not isinstance(job, dict):
            raise RequestError('invalid_job', 'job must be an object')
        if not isinstance(job.get('job_id'), str) or not job['job_id']:
            raise RequestError('invalid_job', 'job_id must be a nonempty string')
        if job.get('station_id') not in self.stations:
            raise RequestError('unknown_station', f'unknown station: {job.get("station_id")!r}')
        ready = job.get('ready_s')
        if type(ready) is not int or not 0 <= ready <= TIME_LIMIT_S:
            raise RequestError('invalid_job', f'ready_s must be an integer in [0, {TIME_LIMIT_S}]')
        return {'job_id': job['job_id'], 'station_id': job['station_id'], 'ready_s': ready}


def _validate_at(at_s):
    if type(at_s) is not int or not 0 <= at_s <= TIME_LIMIT_S:
        raise RequestError('invalid_at_s', f'at_s must be an integer in [0, {TIME_LIMIT_S}]')
    return at_s


def _state_at(row, at):
    if at < row['ready_s']:
        return 'not_ready'
    if at < row['start_s']:
        return 'waiting'
    if at < row['end_s']:
        return 'running'
    return 'simulated_completed'


def _run_of(row):
    return {key: row[key] for key in ('job_id', 'station_id', 'ready_s', 'start_s', 'end_s')}


def _wait_of(row, events):
    wait = {'wait_s': row['start_s'] - row['ready_s']}
    planned = next((event for event in events if event['event'] == 'planned'), None)
    if planned is not None:
        wait['reason'] = planned['detail']['reason']
        wait['station_free_at'] = planned['detail']['station_free_at']
    return wait
