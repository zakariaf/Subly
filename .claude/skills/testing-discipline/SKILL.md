---
name: testing-discipline
description: Use BEFORE adding or changing production code, or anything under tests/. Owns the rule that pure logic is tested directly with the IO mocked, the suite runs with no network and no heavy deps installed, and the sync invariant has explicit tests.
---

# Skill: testing-discipline

Tests cover the logic that can be wrong; IO is mocked. The suite runs anywhere.
Source: `CONTRIBUTING.md` → "Testing".

## When to invoke

Invoke this skill before:
- Adding or changing logic in `subtrans/` (add/adjust a test alongside it).
- Adding or editing anything under `tests/`.
- Changing the translation path (the sync-invariant tests must still hold).
- Reviewing a PR that touches `subtrans/` without touching `tests/`.

## Hard rules

1. **Tests mirror module names.** `tests/test_<module>.py`. Logic in `srt.py` is
   tested in `tests/test_srt.py`, and so on.

2. **Test the pure logic; mock the IO.** We test `srt`, `translate`, and `config`
   directly. Network is stubbed with a fake client (the `_FakeClient` in
   `tests/test_translate.py`), not the real SDK. ffmpeg and Telegram are not unit
   tested — that's why the logic lives in importable modules, not in `bot.py`.

3. **The suite runs with no API key, no network, and no heavy deps installed.**
   `openai`, `telegram`, and `faster_whisper` may be absent; tests must still pass
   because those imports are lazy. A test that requires them installed is in the
   wrong layer.

4. **Cover edges and invariants, not just the happy path.** Timestamp
   rounding/clamping, malformed and markdown-fenced LLM output, env type coercion,
   and — critically — the sync invariant.

5. **The sync invariant has dedicated, permanent tests.** Any change to the
   translation path must keep `test_missing_ids_fall_back_to_original` and
   `test_output_is_never_shorter_than_input` green. New segment transforms ship
   with a test proving they preserve count and order.

6. **`pytest` must be green before every push.** A PR that changes `subtrans/`
   without a matching test change explains why in the description.

7. **Mock at the seam we own.** Patch `translate._make_client` to return a fake
   client; don't patch `openai.OpenAI`. Tests that reach below our own boundary
   break on every internal refactor.

## The shape

```python
# A fake client — no network, no openai install needed.
class _FakeClient:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))

def test_missing_ids_fall_back_to_original(monkeypatch):
    monkeypatch.setattr(
        translate, "_make_client",
        lambda cfg: _FakeClient('{"segments":[{"id":0,"text":"Hola"}]}'),
    )
    segs = [Segment(0, 1, "Hello"), Segment(1, 2, "World")]
    out = translate.translate_segments(segs, "Spanish", Config())
    assert out == ["Hola", "World"]   # id 1 had no translation -> original kept
```

```python
# Config tests clear the env first so the host environment can't leak in.
def test_defaults(monkeypatch):
    _clear_env(monkeypatch)
    assert Config.from_env().transcribe_backend == "local"
```

## Anti-patterns to flag

- ✗ A change to `subtrans/` logic with no test added or updated.
- ✗ A unit test that makes a real network call or needs an API key.
- ✗ A test that imports / mocks `openai.OpenAI` instead of patching `_make_client`.
- ✗ A test that fails when `openai` / `telegram` / `faster_whisper` aren't installed.
- ✗ Touching the translation path without re-running the sync-invariant tests.
- ✗ A config test that reads the host env instead of clearing it via `monkeypatch`.
- ✗ Asserting on a private helper's internals instead of the public function's output.
- ✗ A skipped/`xfail` test with no tracking note.

## Why these rules

The product's correctness is the sync invariant and the parsing edge cases — and
both are pure logic, so both are cheap to test exhaustively. Keeping the suite free
of network and heavy installs means it runs in CI and on a laptop in under a second,
so people actually run it. Mocking at our own seam (`_make_client`) instead of the
SDK is what lets us refactor the client internals without rewriting every test.
