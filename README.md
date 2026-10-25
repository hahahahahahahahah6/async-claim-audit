# async-claim-audit

Audit documented awaitability promises against static Python evidence.

A standard-library-only, offline checker for documentation contracts. It never executes inspected code, uses no network, and never reads `.env` contents. Symlinked files and directories are skipped; inspected files stay inside the supplied tree.

## Usage

```sh
python3 -m pip install .
async-claim-audit path/to/project
python3 -m async_claim_audit path/to/project --json
async-claim-audit path/to/project --ignore 'vendor/*' --verbose --fail-on HIGH
async-claim-audit --version
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
```

The optional path defaults to the current directory. `--ignore` accepts repeatable relative-path globs, including directory paths; ignoring a directory prunes its subtree. `--verbose` includes evidence in text output. JSON always includes `findings`, `verified_claims`, and parse `errors`. Findings include rule, severity, claim sentences and evidence locations. Exit codes: 0 passes the severity threshold, 2 fails it, 1 indicates usage, filesystem, decoding or parsing errors. MEDIUM is the default threshold; HIGH allows MEDIUM findings without failing.

## Rules

| Rule | Severity | Condition |
| --- | --- | --- |
| `documented-async-claim-false` | HIGH | Positive promise with no production evidence |
| `documented-async-claim-false-test-only` | MEDIUM | Positive promise supported only by tests or fixtures |
| `documented-sync-claim-false` | HIGH | Synchronous promise contradicted by production evidence |
| `documented-sync-claim-false-test-only` | MEDIUM | Synchronous promise with evidence only in tests or fixtures |

One finding is emitted per family, with all associated claim sentences and relevant evidence. A family with no production Python source gets a HIGH finding carrying `no-source`, overriding the test-only rule. Both families are evaluated independently. A positive promise with production evidence is verified; a synchronous promise with no evidence anywhere is verified. With no claims, any amount of evidence passes (assuming readable, parseable input).

## Documentation matching

Only root `README.md` and `docs/**/*.md` are checked. Fenced blocks are excluded; inline code counts as prose. Sentences are lowercased, contractions ending in `n't` expand to ` not`, hyphens become spaces, and whitespace collapses. Matching uses exact phrases with word boundaries. Synchronous phrases are matched first and their spans masked before positive matching. Any negation word (`no`, `not`, `never`, `without`) suppresses positive matching for that sentence, while listed synchronous negations still count.

The full phrase vocabulary and illustrative edge cases are below. Phrase lists are deliberately fenced so this tool can audit itself without manufacturing claims.

```text
ASYNC:
async support; supports async; async api; asyncio support;
supports asyncio; asyncio compatible; async compatible; fully async;
async first; async interface; async client; asyncio client;
asynchronous api; asynchronous support; awaitable api; can be awaited
SYNC:
synchronous api; sync api; synchronous interface; synchronous client;
synchronous only; sync only; blocking api; blocking only;
runs synchronously; no async support; no asyncio support;
does not support async; does not support asyncio; not async;
not asyncio compatible

no async support -> sync only (overlap masking)
isn't async -> is not async -> sync
async-first -> async first -> async
never async -> no claim (intentional negation asymmetry)
async -> no claim; asyncio -> no claim
```

## Evidence

| AST evidence | Kind |
| --- | --- |
| `async def`, including nested functions and methods | async-def |
| `await` expression | await |
| `async with` statement | async-with |
| `async for` statement | async-for |
| Dotted calls to `asyncio.run`, `asyncio.create_task`, `asyncio.gather`, `asyncio.ensure_future`, `asyncio.wait` | asyncio-call |
| Calls with terminal names ending in `AsyncClient` or `AsyncSession` | async-constructor |

Evidence is deduplicated by relative path, line, and kind. Production excludes `tests/`, `fixtures/`, `test_*.py`, `*_test.py`, `docs/`, `examples/`, and symlinks. Tests and fixtures provide separate evidence; docs and examples provide none. Common environment, build and version-control directories are pruned.

## Differentiation

- concurrency-claim-audit checks existence of parallelism, never awaitability.
- api-claim-audit checks symbol existence and signatures, never awaitability.
- thread-safety-claim-audit checks synchronisation, never awaitability.
- Bandit and Ruff detect code issues, never documentation promises.
- The asyncio, AnyIO and Trio documentation explains primitives and runtimes, never documentation-versus-code truth.

## Honest limitations

This is exact-phrase and project-wide evidence matching, not symbol-level contract verification. Dead code counts, including uncalled definitions. Presence of machinery cannot establish that a particular documented callable is awaitable or correct.

A bare `import asyncio` or `from asyncio import ...` does not count. Bare names, comments and string literals do not count. A plain function returning an already-built coroutine does not count by itself. Third-party decorators and context managers, including AnyIO and Trio task groups, are not inferred beyond the named constructor rule. An asynchronous route written with `async def` is covered normally.

Only the exact dotted asyncio calls in the table count: aliases and bare `run(...)` calls are not resolved. Constructor matching is an intentional over-approximation; receiver types are not inferred. A synchronous wrapper calling `asyncio.run(...)` counts as evidence and contradicts a synchronous promise by design. Syntax errors are reported with exit 1 rather than treated as a successful audit. Parsing follows the interpreter running the tool; inspected syntax must be supported by that interpreter.

## License

MIT.
