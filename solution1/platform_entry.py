"""平台契约适配器：读取一个请求，写出一个响应后退出。

用法（由 check_platform.py 按 adapter.json 追加参数调用）：
python platform_entry.py --case case.json --db shared.db --request r.json --response w.json
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
    parser.add_argument('--request', required=True)
    parser.add_argument('--response', required=True)
    args = parser.parse_args()
    response = handle(args)
    Path(args.response).write_text(json.dumps(response, ensure_ascii=False), encoding='utf-8')


def handle(args):
    try:
        request = json.loads(Path(args.request).read_text(encoding='utf-8'))
        case = load_case(args.case)
        store = PlanStore(args.db)
        try:
            store.bind_case(canonical_signature(case))
            service = TaskService(store, StationScheduler(store), case['stations'])
            return service.handle(request)
        finally:
            store.close()
    except RequestError as error:
        return error.response()
    except Exception as error:
        return {'status': 'error', 'code': 'internal_error', 'message': f'{type(error).__name__}: {error}'}


if __name__ == '__main__':
    main()
