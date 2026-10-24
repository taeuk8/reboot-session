"""Portable plan storage; no Windows side effects in this module."""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1
KINDS = {'app', 'folder', 'excel', 'chrome', 'terminal'}


def now():
    return datetime.now(timezone.utc).isoformat()


def data_dir():
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'RebootSession'


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2)
    fd, temporary = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if json.loads(Path(temporary).read_text(encoding='utf-8')) != value:
            raise ValueError('저장 검증 실패')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def item(kind, label, payload, detail='', selected=True, warning=''):
    identity = json.dumps([kind, payload], sort_keys=True, ensure_ascii=False)
    return dict(id=hashlib.sha256(identity.encode()).hexdigest()[:20], kind=kind,
                label=label, payload=payload, detail=detail, selected=selected, warning=warning)


def plan(items, warnings=()):
    return dict(version=VERSION, id=str(uuid.uuid4()), created_at=now(),
                owner=os.environ.get('USERDOMAIN', '') + '\\' + os.environ.get('USERNAME', ''),
                items=items, warnings=list(warnings))


def validate(value):
    if value.get('version') != VERSION or not isinstance(value.get('items'), list):
        raise ValueError('지원하지 않는 복원 계획입니다.')
    try:
        if str(uuid.UUID(value['id'])) != value['id']:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError('잘못된 계획 ID입니다.')
    ids = set()
    for row in value['items']:
        if row.get('kind') not in KINDS or not isinstance(row.get('payload'), dict):
            raise ValueError('잘못된 복원 항목입니다.')
        if not isinstance(row.get('id'), str) or row['id'] in ids:
            raise ValueError('복원 항목 ID가 중복되거나 잘못되었습니다.')
        ids.add(row['id'])
        if not isinstance(row.get('selected'), bool):
            raise ValueError('선택 상태가 잘못되었습니다.')
    return value


def fingerprint(items):
    # User selection and display text do not change the underlying work state.
    raw = sorted(json.dumps([r['kind'], r['payload']], sort_keys=True, ensure_ascii=False) for r in items)
    return hashlib.sha256('\n'.join(raw).encode()).hexdigest()


def validate_task(task):
    if not task.get('name') or not task.get('cwd'):
        raise ValueError('작업 이름과 작업 폴더가 필요합니다.')
    if task.get('tool') not in ('shell', 'codex', 'opencode', 'command'):
        raise ValueError('지원하지 않는 도구입니다.')
    if task['tool'] in ('codex', 'opencode') and not task.get('session'):
        raise ValueError('정확한 대화를 열려면 세션 ID가 필요합니다.')
    if task['tool'] == 'command' and not task.get('command'):
        raise ValueError('실행할 명령이 필요합니다.')
    if task.get('environment', 'windows') not in ('windows', 'wsl'):
        raise ValueError('지원하지 않는 실행 환경입니다.')
    return task


class RestoreEngine:
    """Write intent before launch. Ambiguous launches require explicit user retry."""
    def __init__(self, root, launch):
        self.root, self.launch = Path(root), launch

    def run(self, saved, retry=False, notify=lambda *args: None):
        validate(saved)
        path = self.root / ('result-' + saved['id'] + '.json')
        result = read_json(path) if path.exists() else {'plan_id': saved['id'], 'items': {}}
        for row in saved['items']:
            if not row['selected']:
                continue
            previous = result['items'].get(row['id'], {}).get('state')
            if previous == 'launched' or (previous in ('launching', 'failed') and not retry):
                notify(row['id'], previous, '기존 실행 기록 유지')
                continue
            result['items'][row['id']] = {'state': 'launching', 'at': now()}
            atomic_write(path, result)
            try:
                detail = self.launch(row)
                state = 'launched'
            except Exception as error:
                state, detail = 'failed', str(error)
            result['items'][row['id']] = {'state': state, 'detail': detail, 'at': now()}
            atomic_write(path, result)
            notify(row['id'], state, detail)
        return result
