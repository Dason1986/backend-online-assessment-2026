"""一键实验编排：对照实验、反例、接续与重复导入、平台一致性。

产物全部写入 evidence/；每个实验用全新数据库，避免状态串扰。
用法：python experiments/run_experiments.py
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
MATERIALS = ROOT.parent / '第一题材料'
EVIDENCE = ROOT / 'evidence'
PYTHON = sys.executable


def run(title, argv, expect_zero=True):
    print(f'== {title}\n$ {" ".join(argv)}')
    result = subprocess.run([PYTHON, *argv], cwd=ROOT, capture_output=True, text=True)
    if expect_zero and result.returncode != 0:
        raise SystemExit(f'{title} failed:\n{result.stdout}\n{result.stderr}')
    print(result.stdout.strip() or result.stderr.strip(), '\n')
    return result.stdout


def check_result(case, output, name):
    text = run(f'check_result: {name}', [str(MATERIALS / 'check_result.py'), str(case), str(output)])
    (EVIDENCE / f'{name}.json').write_text(text, encoding='utf-8')
    return json.loads(text)


def clean_databases():
    for name in ('fixed.db', 'resume.db', 'mini_global.db', 'mini_station.db'):
        path = EVIDENCE / name
        if path.exists():
            path.unlink()


def main():
    EVIDENCE.mkdir(exist_ok=True)
    clean_databases()
    case = MATERIALS / 'case.json'
    mini_case = ROOT / 'experiments' / 'mini_case.json'
    summary = {}

    run('复跑 legacy 基线（全局时间轴策略，全新库）',
        [str(MATERIALS / 'legacy_backend.py'), '--case', str(case),
         '--db', str(EVIDENCE / 'baseline_rerun.db'), '--out', str(EVIDENCE / 'baseline_rerun.json')])
    summary['baseline'] = check_result(case, EVIDENCE / 'baseline_rerun.json', 'check_baseline')

    run('修复后全量导入（按工位策略，全新库）',
        [str(ROOT / 'batch_entry.py'), '--case', str(case),
         '--db', str(EVIDENCE / 'fixed.db'), '--out', str(EVIDENCE / 'fixed_result.json')])
    summary['fixed'] = check_result(case, EVIDENCE / 'fixed_result.json', 'check_fixed')

    run('反例A-全局策略跑 mini case（legacy 原型）',
        [str(MATERIALS / 'legacy_backend.py'), '--case', str(mini_case),
         '--db', str(EVIDENCE / 'mini_global.db'), '--out', str(EVIDENCE / 'mini_global.json')])
    run('反例A-按工位策略跑同一 mini case',
        [str(ROOT / 'batch_entry.py'), '--case', str(mini_case),
         '--db', str(EVIDENCE / 'mini_station.db'), '--out', str(EVIDENCE / 'mini_station.json')])
    summary['counterexample_global'] = check_result(mini_case, EVIDENCE / 'mini_global.json', 'check_mini_global')
    summary['counterexample_per_station'] = check_result(mini_case, EVIDENCE / 'mini_station.json', 'check_mini_station')
    overlap_text = run('反例B-重叠计划的合法性检查（预期 invalid）',
                       [str(MATERIALS / 'check_result.py'), str(mini_case),
                        str(ROOT / 'experiments' / 'overlap_result.json')], expect_zero=False)
    (EVIDENCE / 'check_overlap.json').write_text(overlap_text, encoding='utf-8')
    summary['counterexample_overlap'] = json.loads(overlap_text)

    resume_db = EVIDENCE / 'resume.db'
    run('接续第一步：只规划 20 个新任务后正常退出',
        [str(ROOT / 'batch_entry.py'), '--case', str(case), '--db', str(resume_db),
         '--out', str(EVIDENCE / 'resume_step1.json'), '--max-new', '20'])
    run('接续第二步：新进程读同一存储完成剩余任务',
        [str(ROOT / 'batch_entry.py'), '--case', str(case), '--db', str(resume_db),
         '--out', str(EVIDENCE / 'resume_final.json')])
    run('接续第三步：再次导入同一输入，验证幂等',
        [str(ROOT / 'batch_entry.py'), '--case', str(case), '--db', str(resume_db),
         '--out', str(EVIDENCE / 'resume_reimport.json')])

    from compare_plans import compare_plans
    summary['resume'] = {
        'step1_vs_final': compare_plans(EVIDENCE / 'resume_step1.json', EVIDENCE / 'resume_final.json'),
        'reimport_vs_final': compare_plans(EVIDENCE / 'resume_reimport.json', EVIDENCE / 'resume_final.json'),
    }

    run('平台一致性检查（独立进程、临时库）',
        [str(MATERIALS / 'check_platform.py'), '--adapter', str(ROOT / 'adapter.json'),
         '--case', str(case), '--out', str(EVIDENCE / 'platform_evidence.json')])
    summary['platform_passed'] = json.loads(
        (EVIDENCE / 'platform_evidence.json').read_text(encoding='utf-8'))['passed']

    (EVIDENCE / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'baseline_first_hour': summary['baseline']['completed_within_horizon'],
                      'fixed_first_hour': summary['fixed']['completed_within_horizon'],
                      'resume_ok': all(v['subset_rows_identical'] for v in summary['resume'].values()),
                      'platform_passed': summary['platform_passed']}, ensure_ascii=True))


if __name__ == '__main__':
    main()
