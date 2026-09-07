"""Check the local layout, frozen disclosure, and absence of publishing triggers.

Usage: uv run python tools/checks/workspace_audit.py [--json] [--self-test]
This complements doc_audit's API/semantic checks; it never rebuilds public/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def snapshot_errors(folder: Path) -> list[str]:
    try:
        manifest = json.loads((folder / 'SNAPSHOT.json').read_text(encoding='utf-8'))
        entries = manifest['files']
        if not entries:
            raise ValueError('empty manifest')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f'Cannot read nonempty disclosure manifest: {exc}']
    errors, seen = [], set()
    for entry in entries:
        rel = entry['path']
        path = folder / rel
        if rel in seen or not path.resolve().is_relative_to(folder.resolve()):
            errors.append(f'Invalid snapshot path: {rel}')
            continue
        seen.add(rel)
        if path.is_symlink() or not path.is_file():
            errors.append(f'Snapshot file missing or symlinked: {rel}')
        elif hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            errors.append(f'Snapshot content changed: {rel}')
    extras = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    extras -= seen | {'SNAPSHOT.json', 'AI_披露断面说明.md'}
    errors.extend(f'Unexpected disclosure file: {name}' for name in sorted(extras))
    return errors


def readme_errors(path: Path) -> list[str]:
    text = path.read_text(encoding='utf-8')
    disclosure = re.compile(r'https?://(?:fuhehe12\.github\.io|github\.com/fuhe(?:he)?12/cc-wire-analyzer)', re.I)
    errors = [f'Disclosure link remains in {path}' for _ in disclosure.finditer(text)]
    for href in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
        href = href.strip('<>').split('#')[0]
        if not href or re.match(r'[a-z]+:', href, re.I):
            continue
        target = (path.parent / href).resolve()
        if target.is_relative_to(ROOT) and 'public' in target.relative_to(ROOT).parts:
            errors.append(f'Readme links to frozen disclosure: {path}: {href}')
        if not target.exists():
            errors.append(f'Broken readme link: {path}: {href}')
    return errors


def audit() -> dict:
    errors = snapshot_errors(ROOT / 'public')
    required = ['README.md', 'CLAUDE.md', 'CHANGELOG.md', 'docs/README.md',
                'docs/development/开发约定.md', 'docs/development/架构总览.md',
                'docs/usage/AI_USAGE.md', 'docs/usage/API契约.md',
                'docs/usage/界面导览.md', 'docs/usage/报文解读.md',
                'docs/guides/同类工具构建手册.md', 'docs/product/data/product-v3.json',
                'tools/build/build_manual.py', 'tools/checks/doc_audit.py']
    errors.extend(f'Required current file missing: {name}' for name in required if not (ROOT / name).is_file())
    retired = ['docs/reference', 'docs/product-manual.html', 'handbook', 'research',
               'site', 'qa', 'README.zh.md', 'README.ja.md', '.github/workflows/pages.yml']
    errors.extend(f'Retired maintenance path still exists: {name}' for name in retired if (ROOT / name).exists())
    errors.extend(f'Test still mixed into runtime source: {p.name}' for p in (ROOT / 'src').glob('*selftest.py'))
    readmes = [ROOT / 'README.md']
    for folder in ('docs', 'tools', 'tests', 'local/notes'):
        readmes.extend((ROOT / folder).rglob('README*.md'))
    for p in readmes:
        if p.is_file():
            errors.extend(readme_errors(p))
    # 260908：发版恢复启用，所以 `push: tags:` 与 `contents: write` 不再是错误——
    # 它们正是发 Release 需要的。仍然禁止的三件事，各自防一个具体的坑：
    #   · `pages: write` —— 部署 Pages 等于更新公开披露面，而 `public/` 是冻结快照
    #   · `schedule:`    —— 无人值守的定时任务会在没人看的时候改动对外产物
    #   · `push: branches:` —— 每次提交都发布，等于取消「验证通过再发」这道人工闸门
    for p in (ROOT / '.github/workflows').glob('*.yml'):
        text = p.read_text(encoding='utf-8')
        if 'pages: write' in text:
            errors.append(f'Pages deployment capability remains (public/ is frozen): {p.name}')
        if re.search(r'^\s*schedule:', text, re.M):
            errors.append(f'Unattended scheduled trigger remains: {p.name}')
        rows = text.splitlines()
        for n, row in enumerate(rows):
            if not re.match(r'^\s*push:\s*$', row):
                continue
            # push: 下面紧跟的几行就是它的触发范围，看有没有 branches:
            if any(re.match(r'^\s*branches:', x) for x in rows[n + 1:n + 6]):
                errors.append(f'Publishes on every branch push (release should be tag-gated): {p.name}')
    return {'ok': not errors, 'errors': errors, 'readmes_checked': len(readmes),
            'scope': 'Current local layout and immutable disclosure; no runtime semantic claims.'}


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        p = folder / 'README.md'
        p.write_bytes(b'frozen')
        manifest = {'files': [{'path': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}]}
        (folder / 'SNAPSHOT.json').write_text(json.dumps(manifest), encoding='utf-8')
        assert not snapshot_errors(folder)
        p.write_bytes(b'changed')
        assert any('changed' in e for e in snapshot_errors(folder))
        p.unlink()
        assert any('missing' in e for e in snapshot_errors(folder))
        p.write_bytes(b'frozen')
        extra = folder / 'unexpected.txt'
        extra.write_text('extra')
        assert any('Unexpected' in e for e in snapshot_errors(folder))
        extra.unlink()
        manifest['files'].append(manifest['files'][0])
        (folder / 'SNAPSHOT.json').write_text(json.dumps(manifest))
        assert any('Invalid' in e for e in snapshot_errors(folder))
    print('workspace_audit: 5 integrity cases passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        result = audit()
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
              '\n'.join(result['errors']) if result['errors'] else 'Workspace and disclosure checks passed')
        raise SystemExit(0 if result['ok'] else 1)
