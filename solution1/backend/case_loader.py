"""case.json 加载与输入域校验：非法输入在此明确报错，不进入计划层。"""
import json
from pathlib import Path

TIME_LIMIT_S = 2**63 - 1


def _require_time(value, name, minimum=0):
    if type(value) is not int or not minimum <= value <= TIME_LIMIT_S:
        raise ValueError(f'{name} must be an integer in [{minimum}, {TIME_LIMIT_S}]')


def load_case(path):
    case = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(case, dict):
        raise ValueError('case must be an object')
    _require_time(case['report_horizon_s'], 'report_horizon_s', minimum=1)
    stations = case['stations']
    if not isinstance(stations, dict) or not stations:
        raise ValueError('stations must be a nonempty object')
    for station, spec in stations.items():
        if type(spec.get('cycle_s')) is not int or spec['cycle_s'] <= 0:
            raise ValueError(f'station {station}: cycle_s must be a positive integer')
    jobs = case['jobs']
    if not isinstance(jobs, list):
        raise ValueError('jobs must be an array')
    seen = {}
    for job in jobs:
        _validate_job_shape(job, stations)
        previous = seen.get(job['job_id'])
        if previous is not None and previous != job:
            raise ValueError(f'same job_id with conflicting payload: {job["job_id"]}')
        seen[job['job_id']] = job
    return case


def _validate_job_shape(job, stations):
    if not isinstance(job, dict):
        raise ValueError('job must be an object')
    if not isinstance(job.get('job_id'), str) or not job['job_id']:
        raise ValueError('job_id must be a nonempty string')
    if job.get('station_id') not in stations:
        raise ValueError(f'unknown station: {job.get("station_id")}')
    _require_time(job.get('ready_s'), f'job {job.get("job_id")}: ready_s')


def unique_jobs(case):
    seen, ordered = set(), []
    for job in case['jobs']:
        if job['job_id'] not in seen:
            seen.add(job['job_id'])
            ordered.append(job)
    return ordered


def canonical_signature(case):
    return json.dumps(case, sort_keys=True, separators=(',', ':'))
