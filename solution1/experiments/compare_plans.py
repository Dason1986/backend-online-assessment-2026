"""比较两份导出计划的集合关系，用于接续与重复导入一致性证据。"""
import json
from pathlib import Path

RUN_FIELDS = ('job_id', 'station_id', 'ready_s', 'start_s', 'end_s')


def load_runs(path):
    rows = json.loads(Path(path).read_text(encoding='utf-8'))['runs']
    return {row['job_id']: tuple(row[key] for key in RUN_FIELDS) for row in rows}


def compare_plans(path_subset, path_full):
    subset, full = load_runs(path_subset), load_runs(path_full)
    mismatched = sorted(jid for jid, row in subset.items() if full.get(jid) != row)
    return {'subset_count': len(subset), 'full_count': len(full),
            'subset_rows_identical': not mismatched,
            'mismatched_job_ids': mismatched,
            'duplicate_plan_rows': len(full) != len(set(full.values())),
            'missing_in_full': sorted(set(subset) - set(full))}
