---
name: python-craft
description: Use BEFORE writing or modifying any Python — it governs naming, function and class design, type hints, comments, and docstrings across the whole codebase. The cross-cutting style skill; it composes with every domain skill.
---

# Skill: python-craft

How we shape code regardless of domain: small functions, honest names, comments
that explain *why*, docstrings that state contracts. Source: `CONTRIBUTING.md` →
"Python style", "Guiding principles".

## When to invoke

Invoke this skill **on every Python change**, alongside the domain skill. It's the
baseline. Pay special attention when:
- Naming a new function, class, constant, variable, or module.
- Deciding whether something should be a function, a class, or a `@dataclass`.
- Adding a comment or a docstring.
- Adding a type hint.

## Hard rules

### Naming
1. **`snake_case`** for functions and variables; **`PascalCase`** for classes
   (`Segment`, `Config`); **`UPPER_CASE`** for module constants (`SYSTEM_PROMPT`,
   `DEFAULT_STYLE`, `STAGE_TEXT`, `SEND_LIMIT_MB`).
2. **`_leading_underscore` marks module-private** helpers (`_get`, `_make_client`,
   `_translate_batch`, `_pick_media`). If it's not part of the module's public
   surface, prefix it.
3. **Names say what the thing is, not how it's built.** `extract_audio`,
   `has_video_stream`, `build_srt`, `translate_segments` — a reader knows the job
   from the name. No `data`, `tmp`, `do_it`, `helper`, `manager`.
4. **No abbreviations that aren't already idioms.** `cfg`, `srt`, `vf` (ffmpeg
   filtergraph) are fine because they're domain-standard; invented short forms are not.

### Functions
5. **One function, one job.** If you need "and" to describe it, split it. The
   pipeline stages are the model: each does exactly one transformation. (Sizing,
   nesting, and single-responsibility in depth are owned by the
   `complexity-and-srp` skill — invoke it too.)
6. **Type-hint every signature**, params and return. Use modern 3.10+ syntax:
   `str | None`, `list[Segment]`, `dict[int, str]` — not `Optional`, `List`, `Dict`.
7. **Return early; keep the happy path un-nested.** Guard clauses over deep `if`/`else`
   (`set_lang` returns on bad input before doing work).
8. **Pass `cfg`, don't reach for globals.** Functions take what they need as
   arguments; the only module-level state is constants and the deliberate
   `_model_cache` (commented).

### Classes
9. **Reach for a function first.** Add a class only when you have state + behavior
   that genuinely belong together. Most of this codebase is functions.
10. **Plain data is a `@dataclass`** (`Segment`, `Config`) — never a hand-written
    `__init__` that just assigns fields.
11. **No single-method classes** that exist only to hold one function. That's a
    function.

### Comments
12. **Default to no comment.** Well-named code is the documentation. Add a comment
    only when the *why* is non-obvious — a hidden constraint or a workaround.
13. **Comments explain WHY, never WHAT.** The good examples already in the tree:
    the `cwd`-based path-escaping note in `video.burn_subtitles`, the 10-minute
    timeout warning in `config.py`, the "ignore message-not-modified" note on the
    bot's status edit.
14. **No commented-out code, no `# TODO` without a tracking note, no comment that
    restates the line below it.**

### Docstrings
15. **Every module has a one-line (or short) docstring** stating its job — see the
    top of every file in `subtrans/`. Keep the "Step N —" framing consistent with
    the existing modules.
16. **Public functions get a docstring stating the contract** — what it returns,
    and any invariant (`translate_segments`: "one per input segment, same order").
    Skip docstrings on obvious private helpers.
17. **Docstrings describe behavior and contracts, not implementation.** If the body
    changes but the contract doesn't, the docstring shouldn't need editing.

### Shape
18. **Simplicity first.** Minimum code that solves the problem — no speculative
    flexibility, no abstraction for a single caller, no error handling for
    impossible cases. If 50 lines would do, don't write 200. (The `complexity-and-srp`
    skill owns the full sizing/over-engineering rules.)

## The shape

```python
# Good: dataclass for plain data, hinted, self-describing.
@dataclass
class Segment:
    start: float  # seconds
    end: float    # seconds
    text: str
```

```python
# Good: docstring states the contract (the invariant), not the mechanics.
def translate_segments(segments: list[Segment], target_language: str, cfg,
                       source_language: str | None = None) -> list[str]:
    """Return a list of translated strings, one per input segment (same order)."""
```

```python
# Good: a comment that earns its place — explains a non-obvious WHY.
# We run ffmpeg with cwd set to the SRT's directory and reference it by
# basename — the `subtitles` filter has fragile path escaping.
```

## Anti-patterns to flag

- ✗ Vague names: `data`, `tmp`, `obj`, `do_stuff`, `helper`, `process`.
- ✗ A public function or method with no type hints, or using `Optional[X]` / `List[X]` instead of `X | None` / `list[X]`.
- ✗ A function that does two things ("translate **and** write the file").
- ✗ A class wrapping a single function, or a hand-written `__init__` that only assigns fields (use `@dataclass`).
- ✗ A comment that restates the code (`# loop over segments`).
- ✗ Commented-out code or a bare `# TODO`.
- ✗ A module with no top docstring, or a public function whose contract isn't documented.
- ✗ Deeply nested `if`/`else` where a guard-clause early return would flatten it.
- ✗ Speculative generality: config knobs, hooks, or abstraction layers with one caller.

## Why these rules

This codebase reads well because it's small, honestly named, and uncommented where
it doesn't need to be. Names and types carry the meaning; comments are reserved for
the handful of genuinely surprising constraints (ffmpeg path escaping, the SDK's
10-minute default, Telegram's size caps). Docstrings state contracts so a caller
never has to read the body. Keeping functions single-purpose is also what makes the
domain skills enforceable — a stage that does one thing is testable, mockable, and
swappable; a 200-line do-everything function is none of those.
