---
name: complexity-and-srp
description: Use BEFORE adding a function, class, or module — and when a diff makes one bigger. Owns the rules on single responsibility, function/class/file size, nesting and branching budgets, cohesion, coupling, and not abstracting before you need to.
---

# Skill: complexity-and-srp

Keep every unit small and about one thing. The cross-cutting "right size and shape"
skill; it composes with `python-craft` (which owns naming/comments/docs) and with
every domain skill. Source: `CONTRIBUTING.md` → "Guiding principles", "Python style".

## When to invoke

Invoke this skill whenever you:
- Add a new function, class, or module.
- Make an existing function/class/file **longer**, more nested, or more branchy.
- Add a parameter, a flag, or a conditional.
- Feel the urge to add an abstraction "for later."

## Hard rules

### Single responsibility
1. **One unit, one reason to change.** A function does one thing, a class models one
   concept, a module owns one stage. The `subtrans/` split is the template:
   `audio` / `transcribe` / `translate` / `srt` / `video` — each is one job.
2. **If you describe it with "and," split it.** "translate **and** write the file",
   "validate **and** send" → two units.
3. **Separate the levels: decide vs. do.** Orchestration functions (which call
   stages and report progress) stay separate from the stages that do the work.
   `pipeline.run` and `bot.handle_media` orchestrate; they delegate every real
   computation to a single-purpose function.

### Size budgets (soft limits — a smell, not a hard gate)
4. **Functions: aim ≲ 40 lines of real logic.** The one tolerated exception is an
   IO-edge orchestrator like `handle_media` — and only because every heavy step is
   already delegated (`asyncio.to_thread(extract_audio …)`, `…(transcribe …)`).
   It is at the *upper bound*; if it grows further, extract helpers (e.g. a
   `_send_results(...)`), don't keep appending.
5. **Classes: small and data-first.** `Segment` and `Config` carry data, not
   sprawling behavior. A class accreting unrelated methods is several classes.
6. **Files: one cohesive concept.** When a module starts mixing concerns or pushes
   past a few hundred lines, split it the way `subtrans/` is split. `bot.py` stays
   the only big file because it's the IO shell, and even it is sectioned
   (Commands / File handling / Wiring).

### Complexity budgets
7. **Nesting ≤ 3 levels.** Use guard clauses and early returns to stay flat
   (`set_output` rejects bad input up front instead of wrapping the body in `if`).
8. **Replace branching with data when the branches are uniform.** A dispatch dict
   beats a chain of `if`s — `STAGE_TEXT` maps stage→message, and `transcribe`
   dispatches on `cfg.transcribe_backend` to one of two functions. Reach for a
   lookup before a fifth `elif`.
9. **Parameter budget ≲ 5.** Past that, the parameters are really one object —
   bundle them (this is exactly why `Config` exists instead of passing ten
   settings around). Prefer keyword-only for clarity when there are several.
10. **One level of abstraction per function.** Don't mix high-level orchestration
    and low-level byte-twiddling in the same body; push the details down a level.

### Don't over-engineer
11. **YAGNI — no abstraction before the second caller.** No base classes, plugin
    hooks, strategy layers, or config knobs for a single use site. The codebase has
    exactly the seams it needs (backend dispatch, env config) and no more.
12. **DRY by the rule of three.** Two similar blocks can wait; extract a helper on
    the third repetition, when the shared shape is actually clear.
13. **Deleting code is a valid way to reduce complexity.** The simplest unit is the
    one you didn't write. If 50 lines would do what 200 do, write 50.

## The shape

```python
# Branching collapsed to a lookup (low complexity, trivially extendable).
STAGE_TEXT = {
    "extract": "🎬 Extracting audio…",
    "transcribe": "🎙 Transcribing…",
    "translate": "🌐 Translating…",
    "build": "📝 Building subtitles…",
}

# Dispatch instead of a long if/elif on backend type.
def transcribe(audio_path, cfg, language=None):
    if cfg.transcribe_backend == "openai":
        return _transcribe_openai(...)
    return _transcribe_local(...)
```

```python
# Many settings -> one object, instead of a 10-parameter function.
@dataclass
class Config:
    whisper_model: str = "small"
    request_timeout: float = 60.0
    ...   # the parameter budget problem, solved by bundling
```

## Anti-patterns to flag

- ✗ A function that does two jobs, or that you can only summarize with "and".
- ✗ A function well past ~40 lines that isn't a thin IO orchestrator delegating its work.
- ✗ `handle_media` (or any orchestrator) growing new inline logic instead of extracting a helper.
- ✗ Nesting deeper than 3 levels where guard clauses would flatten it.
- ✗ A long `if/elif` chain over uniform cases that should be a dispatch dict.
- ✗ A function taking 6+ positional parameters instead of a small object.
- ✗ A class collecting unrelated methods (low cohesion) — split by responsibility.
- ✗ A module mixing concerns or ballooning past a few hundred lines without a split.
- ✗ An abstraction (base class, hook, flag, generic) introduced for a single caller.
- ✗ A helper extracted on the *first* duplication before the shared shape is clear.

## Why these rules

Small, single-purpose units are why the rest of the rulebook is enforceable: a
stage that does one thing is testable in isolation, mockable at a clean seam, and
swappable via config. Complexity compounds — every extra branch, parameter, and
nesting level multiplies the states a reader and a test must consider. And every
premature abstraction is a bet on a future that usually doesn't arrive, paid for
with indirection today. Keep units small now and you keep the option to change them
later; let them sprawl and every future change gets more expensive.
