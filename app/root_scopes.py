"""Work-owned root capabilities; task selections never grant a new root."""
import json
from pathlib import Path
from .path_inputs import validate_external_root


def roots(work):
    return json.loads(work.external_roots or '[]')


def registered(work, path, capability):
    root = validate_external_root(path)
    match = next((item for item in roots(work) if item['path'] == str(root)), None)
    if not match or not match.get(capability, False):
        raise ValueError(f'Work에 등록된 {capability} 권한이 없는 외부 Root입니다: {path}')
    return root, match


def add(work, path, browse=True, read=False, ignore_patterns=()):
    if not browse and not read:
        raise ValueError('탐색 또는 AI 읽기 권한을 선택하세요.')
    root = validate_external_root(path)
    if root == Path(work.linked_workspace_path or work.workspace_path or work.path):
        raise ValueError('Primary Workspace는 외부 Root로 등록할 수 없습니다.')
    items = roots(work)
    existing = next((item for item in items if item['path'] == str(root)), None)
    if existing:
        existing.update(browse=bool(browse), read=bool(read), ignore_patterns=list(ignore_patterns))
    else:
        if len(items) >= 20:
            raise ValueError('외부 Root는 최대 20개까지 등록할 수 있습니다.')
        items.append({'path': str(root), 'browse': bool(browse), 'read': bool(read),
                      'write': False, 'ignore_patterns': list(ignore_patterns)})
    work.external_roots = json.dumps(items, ensure_ascii=False)
    return existing or items[-1]
