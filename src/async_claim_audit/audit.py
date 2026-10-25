"""Offline documentation and AST inspection; never imports audited code."""
import ast
import fnmatch
import re
from pathlib import Path

ASYNC_PHRASES = ('async support', 'supports async', 'async api', 'asyncio support', 'supports asyncio', 'asyncio compatible', 'async compatible', 'fully async', 'async first', 'async interface', 'async client', 'asyncio client', 'asynchronous api', 'asynchronous support', 'awaitable api', 'can be awaited')
SYNC_PHRASES = ('synchronous api', 'sync api', 'synchronous interface', 'synchronous client', 'synchronous only', 'sync only', 'blocking api', 'blocking only', 'runs synchronously', 'no async support', 'no asyncio support', 'does not support async', 'does not support asyncio', 'not async', 'not asyncio compatible')
CALLS = {'asyncio.' + name for name in ('run', 'create_task', 'gather', 'ensure_future', 'wait')}


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def unfenced(text):
    lines, fence, width = [], None, 0
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence and len(match[1]) >= width and not match[2].strip():
                fence = None
            lines.append('')
        elif match:
            fence, width = match[1][0], len(match[1])
            lines.append('')
        else:
            lines.append(line)
    return '\n'.join(lines)


def phrase_pattern(phrase):
    return r'(?<!\w)' + re.escape(phrase) + r'(?!\w)'


def extract_claims(text, path='README.md'):
    claims = []
    for sentence in re.split(r'[.!?]+|\n\s*\n', unfenced(text)):
        normalized = normalize(sentence)
        masked = normalized
        sync = False
        for phrase in sorted(SYNC_PHRASES, key=len, reverse=True):
            pattern = phrase_pattern(phrase)
            if re.search(pattern, masked):
                sync = True
                masked = re.sub(pattern, lambda m: ' ' * len(m[0]), masked)
        if sync:
            claims.append({'family': 'sync', 'path': path, 'sentence': sentence.strip()})
        if not re.search(r'\b(no|not|never|without)\b', normalized):
            if any(re.search(phrase_pattern(p), masked) for p in ASYNC_PHRASES):
                claims.append({'family': 'async', 'path': path, 'sentence': sentence.strip()})
    return claims


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return base + '.' + node.attr if base else ''
    return ''


def extract_evidence(text, path):
    tree = ast.parse(text, filename=path)
    evidence = set()
    kinds = {ast.AsyncFunctionDef: 'async-def', ast.Await: 'await', ast.AsyncWith: 'async-with', ast.AsyncFor: 'async-for'}
    for node in ast.walk(tree):
        kind = kinds.get(type(node))
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            if name in CALLS:
                kind = 'asyncio-call'
            elif name and name.split('.')[-1].endswith(('AsyncClient', 'AsyncSession')):
                kind = 'async-constructor'
        if kind:
            evidence.add((path, node.lineno, kind))
    return [{'path': p, 'line': line, 'kind': kind} for p, line, kind in sorted(evidence)]


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('audit root must be a directory')
    claims, production, testonly, errors = [], [], [], []
    source_count = 0
    def visit(directory):
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or any(fnmatch.fnmatchcase(relative, pat) for pat in ignore):
                continue
            if path.is_dir():
                if path.name not in {'.git', '.venv', 'venv', '__pycache__', 'build', 'dist'}:
                    yield from visit(path)
            else:
                yield path, relative
    for path, relative in visit(root):
        parts = Path(relative).parts
        if relative == 'README.md' or (parts[0] == 'docs' and path.suffix == '.md'):
            claims.extend(extract_claims(path.read_text(encoding='utf-8'), relative))
        if path.suffix != '.py' or path.name == '.env':
            continue
        testing = any(p in {'tests', 'fixtures'} for p in parts[:-1]) or path.name.startswith('test_') or path.name.endswith('_test.py')
        if any(p in {'docs', 'examples'} for p in parts[:-1]):
            continue
        if not testing:
            source_count += 1
        try:
            items = extract_evidence(path.read_text(encoding='utf-8'), relative)
        except (SyntaxError, UnicodeError) as exc:
            errors.append({'path': relative, 'error': str(exc)})
            continue
        (testonly if testing else production).extend(items)
    findings, verified = [], []
    for family in ('async', 'sync'):
        selected = [c for c in claims if c['family'] == family]
        if not selected:
            continue
        severity, evidence, suffix = None, [], ''
        if not source_count:
            severity, evidence = 'HIGH', [{'kind': 'no-source'}]
        elif family == 'async' and not production:
            severity, evidence, suffix = ('MEDIUM', testonly, '-test-only') if testonly else ('HIGH', [], '')
        elif family == 'sync' and production:
            severity, evidence = 'HIGH', production
        elif family == 'sync' and testonly:
            severity, evidence, suffix = 'MEDIUM', testonly, '-test-only'
        if severity:
            findings.append({'rule': 'documented-' + family + '-claim-false' + suffix, 'severity': severity, 'claims': selected, 'evidence': evidence})
        else:
            verified.append({'family': family, 'claims': selected, 'evidence': production if family == 'async' else []})
    return {'findings': findings, 'verified_claims': verified, 'errors': errors}
