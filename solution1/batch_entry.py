"""批量闭环入口：导入 case 全部投递，持久化去重，导出全部唯一任务计划。

--max-new N 限制本次新规划数量，用于分批接续：重复运行同一命令读同一库，
已受理任务返回 duplicate 且计划不变，剩余任务继续规划。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend import PlanStore, RequestError, StationScheduler, TaskService, canonical_signature, load_case


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--max-new', type=int, default=None)
    args = parser.parse_args()
    summary = run_batch(args)
    print(json.dumps(summary, ensure_ascii=True))


def run_batch(args):
    case = load_case(args.case)
    store = PlanStore(args.db)
    try:
        store.bind_case(canonical_signature(case))
        service = TaskService(store, StationScheduler(store), case['stations'])
        stats = submit_all(service, case['jobs'], args.max_new)
        report = service.report(case['report_horizon_s'])
        export = {'runs': report['runs']}
        Path(args.out).write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'submitted': sum(stats.values()), 'accepted': stats['accepted'],
                'duplicate': stats['duplicate'], 'conflict': stats['conflict'],
                'exported_runs': len(report['runs'])}
    finally:
        store.close()


def submit_all(service, deliveries, max_new):
    stats = {'accepted': 0, 'duplicate': 0, 'conflict': 0}
    planned_new = 0
    for index, job in enumerate(deliveries):
        if max_new is not None and planned_new >= max_new:
            break
        result = service.submit(job)
        stats[result['status']] += 1
        if result['status'] == 'accepted':
            planned_new += 1
    return stats


if __name__ == '__main__':
    try:
        main()
    except RequestError as error:
        raise SystemExit(f'{error.code}: {error.message}')
