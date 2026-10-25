import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from async_claim_audit.audit import (ASYNC_PHRASES, SYNC_PHRASES, audit,
                                    extract_claims, extract_evidence, normalize)
from async_claim_audit.__main__ import main


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def project(self, claim='Async support.', source='def f(): return 1\n'):
        self.write('README.md', claim)
        self.write('main.py', source)
        return audit(self.root)

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(self.root), *args])
        return code, output.getvalue()

    def test_normalize(self):
        self.assertEqual(normalize("ISN'T async-first  now"), 'is not async first now')

    def test_fences(self):
        self.assertEqual(extract_claims('```text\nAsync support\n```\n~~~\nsync api\n~~~'), [])

    def test_inline(self):
        self.assertEqual(extract_claims('An `async api` exists.')[0]['family'], 'async')

    def test_overlap(self):
        self.assertEqual([x['family'] for x in extract_claims('no async support')], ['sync'])

    def test_contraction(self):
        self.assertEqual(extract_claims("It isn't async")[0]['family'], 'sync')

    def test_both_async_spellings(self):
        self.assertEqual(len(extract_claims('async-first. async first.')), 2)

    def test_never(self):
        self.assertEqual(extract_claims('never async'), [])

    def test_bare_async(self):
        self.assertEqual(extract_claims('A note on async'), [])

    def test_bare_asyncio(self):
        self.assertEqual(extract_claims('A note on asyncio'), [])

    def test_negated(self):
        self.assertEqual(extract_claims('does not claim to be async'), [])

    def test_without(self):
        self.assertEqual(extract_claims('without async support'), [])

    def test_boundaries(self):
        self.assertEqual(extract_claims('nonasync supportiveness'), [])

    def test_no_optional_middle(self):
        self.assertEqual(extract_claims('supports native async'), [])

    def test_good_async(self):
        result = self.project(source='async def f(): await work()\n')
        self.assertFalse(result['findings'])
        self.assertEqual(result['verified_claims'][0]['family'], 'async')

    def test_good_sync(self):
        result = self.project('Synchronous API.')
        self.assertFalse(result['findings'])
        self.assertEqual(result['verified_claims'][0]['family'], 'sync')

    def test_bad_async(self):
        self.assertEqual(self.project()['findings'][0]['rule'], 'documented-async-claim-false')

    def test_bad_sync(self):
        self.assertEqual(self.project('Sync API.', 'async def f(): pass')['findings'][0]['rule'], 'documented-sync-claim-false')

    def test_testonly_async(self):
        self.project()
        self.write('tests/test_work.py', 'async def f(): pass')
        finding = audit(self.root)['findings'][0]
        self.assertEqual(finding['severity'], 'MEDIUM')
        self.assertTrue(finding['rule'].endswith('-test-only'))

    def test_testonly_sync(self):
        self.project('Sync API.')
        self.write('fixtures/work.py', 'async def f(): pass')
        self.assertEqual(audit(self.root)['findings'][0]['rule'], 'documented-sync-claim-false-test-only')

    def test_both_families(self):
        self.write('README.md', 'Async support. Sync API.')
        result = audit(self.root)
        self.assertEqual(len(result['findings']), 2)
        self.assertTrue(all(f['evidence'] == [{'kind': 'no-source'}] for f in result['findings']))

    def test_no_source(self):
        self.write('README.md', 'Async support.')
        self.write('tests/test_x.py', 'async def f(): pass')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')

    def test_no_claim(self):
        self.assertEqual(self.project('Hello.', 'async def f(): pass')['findings'], [])

    def test_ignore(self):
        self.project('Async support.', 'async def f(): pass')
        self.write('other.py', 'pass')
        self.assertEqual(audit(self.root, ['main.py'])['findings'][0]['severity'], 'HIGH')

    def test_ignore_directory(self):
        self.project()
        self.write('vendor/code.py', 'async def f(): pass')
        self.assertTrue(audit(self.root, ['vendor'])['findings'])

    def test_docs_claim(self):
        self.write('main.py', 'pass')
        self.write('docs/deep/guide.md', 'Async support.')
        self.assertTrue(audit(self.root)['findings'])

    def test_other_docs_excluded(self):
        self.write('OTHER.md', 'Async support.')
        self.assertFalse(audit(self.root)['findings'])

    def test_symlink(self):
        self.project()
        (self.root / 'linked.py').symlink_to(self.write('examples/a.py', 'async def f(): pass'))
        self.assertTrue(audit(self.root)['findings'])

    def test_env_never_opened(self):
        self.project()
        self.write('.env', 'SECRET_MARKER_MUST_NOT_APPEAR')
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotEqual(path.name, '.env')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            code, output = self.cli('--json')
        self.assertEqual(code, 2)
        self.assertNotIn('SECRET_MARKER', output)

    def test_json(self):
        self.project()
        code, output = self.cli('--json')
        self.assertEqual(code, 2)
        self.assertTrue({'findings', 'verified_claims'} <= json.loads(output).keys())

    def test_threshold(self):
        self.project()
        self.write('tests/test_work.py', 'async def f(): pass')
        self.assertEqual(self.cli('--fail-on', 'HIGH')[0], 0)
        self.assertEqual(self.cli()[0], 2)

    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as cm:
            main(['--version'])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), '0.1.0')

    def test_usage(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            main(['--unknown'])
        self.assertEqual(cm.exception.code, 1)

    def test_parse_error(self):
        self.project(source='def broken(')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.cli('--json')[0], 1)

    def test_all_evidence(self):
        result = self.project('Sync API.', 'async def f():\n await x()\n async with x(): pass\n async for y in x(): pass\n')
        self.assertEqual(len(result['findings'][0]['evidence']), 4)

    def test_one_finding_many_claims(self):
        result = self.project('Async support. Fully async.')
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(len(result['findings'][0]['claims']), 2)

    def test_self_audit(self):
        result = audit(Path(__file__).resolve().parents[1])
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['verified_claims'], [])


def phrase_test(phrase, family):
    def test(self):
        self.assertEqual({c['family'] for c in extract_claims(phrase)}, {family})
    return test


for family, phrases in [('async', ASYNC_PHRASES), ('sync', SYNC_PHRASES)]:
    for index, phrase in enumerate(phrases):
        setattr(AuditTests, 'test_phrase_' + family + '_' + str(index), phrase_test(phrase, family))


def evidence_test(source, expected):
    def test(self):
        self.assertEqual({e['kind'] for e in extract_evidence(source, 'main.py')}, expected)
    return test


CASES = [
    ('async def f(): pass', {'async-def'}),
    ('async def f(): await x()', {'async-def', 'await'}),
    ('async def f():\n async with x(): pass', {'async-def', 'async-with'}),
    ('async def f():\n async for x in y: pass', {'async-def', 'async-for'}),
    ('asyncio.run(f())', {'asyncio-call'}),
    ('asyncio.create_task(f())', {'asyncio-call'}),
    ('asyncio.gather(f())', {'asyncio-call'}),
    ('asyncio.ensure_future(f())', {'asyncio-call'}),
    ('asyncio.wait(f())', {'asyncio-call'}),
    ('run(f())', set()), ('AsyncClient()', {'async-constructor'}),
    ('httpx.AsyncClient()', {'async-constructor'}),
    ('AsyncSession()', {'async-constructor'}),
    ('import asyncio', set()), ('from asyncio import run', set()),
    ('def f(): return 1', set()), ('def f(): return coroutine', set()),
    ('# async def\nx = "async"', set()),
    ('def f():\n async def inner(): pass', {'async-def'}),
    ('asyncio.run(f()); asyncio.run(g())', {'asyncio-call'}),
]
for index, (source, expected) in enumerate(CASES):
    setattr(AuditTests, 'test_evidence_' + str(index), evidence_test(source, expected))


def excluded_test(name):
    def test(self):
        self.project()
        self.write(name, 'async def f(): pass')
        result = audit(self.root)
        self.assertEqual(result['findings'][0]['severity'], 'MEDIUM' if name.startswith(('tests/', 'fixtures/', 'test_', 'x_test')) else 'HIGH')
    return test


for index, name in enumerate(['tests/x.py', 'fixtures/x.py', 'test_x.py', 'x_test.py', 'docs/x.py', 'examples/x.py']):
    setattr(AuditTests, 'test_excluded_' + str(index), excluded_test(name))
