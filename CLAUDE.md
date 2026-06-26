# CLAUDE.md — AI collaboration rules for Subly

This document is the **non-negotiable contract** for any AI assistant working on this
codebase. Read it before any other file. Re-read it before any non-trivial change.

If you find yourself wanting to make an exception, **stop and ask the user.**
Exceptions to these rules are decisions for humans.

Three documents work together:
- **`CLAUDE.md`** (this file) — the project contract, the working principles, and the
  skill router.
- **`.claude/skills/*/SKILL.md`** — the canonical, enforceable per-domain rules. **On
  any conflict, the skill wins for its domain** (it's more specific).
- **`CONTRIBUTING.md`** — the human-readable companion the skills cite. Same rules,
  prose form, for developers.

## Working principles

These four principles are the foundation — they apply to **every** task here, before
any specific rule. The project rules further down are how we operationalize them; they
never relax them. If a specific rule ever appears to contradict one of these, **the
principle wins — stop and ask.**

### P1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.** Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask. (See §7.)

### P2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**
- No features beyond what was asked. No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
- Senior-engineer test: "Would they call this overcomplicated?" If yes, simplify.
- Enforced in depth by the `complexity-and-srp` skill and §5 (what NOT to build).

### P3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**
- Don't "improve" adjacent code, comments, or formatting. Don't refactor what isn't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- Remove imports/vars/functions *your* change orphaned; leave pre-existing dead code.
- The test: every changed line traces directly to the user's request. (See §4.4.)

### P4. Goal-Driven Execution

**Define success criteria. Loop until verified.** Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass."
- "Fix the bug" → "Write a test that reproduces it, then make it pass."
- "Refactor X" → "Ensure tests pass before and after."
- For multi-step tasks, state a brief plan with a `verify:` check per step.
- Enforced by §4.1 (TDD) and the `testing-discipline` skill.

## 0. Skills are mandatory — invoke before coding

This project ships **seven project-scoped skills** in `.claude/skills/`. They encode
the load-bearing patterns of this codebase. **You MUST invoke the relevant skill
before writing or modifying code in its domain.** Skipping a skill is a process
violation equivalent to skipping `CLAUDE.md`.

### STOP — load the skill *before* you edit (hard gate)

**Loading comes first, editing second.** Before your **first** `Edit`/`Write` to a
file in this session, you MUST have read the mapped `SKILL.md`(s) **in this session**.
If you are about to touch a file below and have not read its skill, **STOP and read it
now** — do not edit first and read later. Editing a file without having loaded its
skill is a rule violation: undo and restart the task correctly.

| If you are about to edit… | You MUST have read first |
| --- | --- |
| `subtrans/audio.py`, `srt.py`, `video.py`, `pipeline.py` | `subtitle-pipeline` |
| `subtrans/translate.py` | `subtitle-pipeline` + `llm-translation` |
| `subtrans/transcribe.py` | `subtitle-pipeline` + `llm-translation` |
| `bot.py` | `telegram-bot` |
| `cli.py` | `telegram-bot` (entry-point rules apply) |
| `subtrans/config.py`, `.env.example` | `config-and-secrets` |
| `tests/**`, `pyproject.toml` | `testing-discipline` |
| **any `*.py` — always, on top of the rows above** | `python-craft` + `complexity-and-srp` |

Then **state which skills you loaded** in your first response (see "How to invoke").
If you realize mid-task that you're editing a file whose skill you haven't read, stop
and read it before the next change. (What each skill covers is in §8.)

### How to invoke

When you start a task, identify which skills apply, then **state explicitly which
skills you are invoking** in your first response, e.g.:

> "Adding a `/srt`-only fast path to the bot. Invoking `telegram-bot`,
> `subtitle-pipeline`, `testing-discipline`, `python-craft`, and `complexity-and-srp`."

If the user invokes a skill manually with `/<skill-name>`, treat it as a load-bearing
instruction — its rules supersede your default behavior.

### What "invoke" means in practice

1. **Read the skill's `SKILL.md` fully** before writing code — the file, not the summary.
2. **Apply its "Hard rules"** to your code. They are not suggestions.
3. **Run its "Anti-patterns to flag" checklist** against your diff before submitting.
   Your diff must not match any of them.
4. **Cite the skills in the PR/commit description** when their rules shaped the work.

### Multi-skill tasks

Most non-trivial tasks invoke 3–5 skills. Examples:
- New bot command that changes output → `telegram-bot` + `config-and-secrets` + `testing-discipline` + `python-craft` + `complexity-and-srp`.
- Adding a translation-quality tweak → `llm-translation` + `subtitle-pipeline` (the invariant) + `testing-discipline` + craft pair.
- A new transcription backend → `subtitle-pipeline` + `config-and-secrets` + `testing-discipline` + craft pair.

Skills compose; they don't conflict. If two appear to contradict, **stop and ask** —
that means a skill file needs fixing, not that you ignore one.

### When NOT to invoke a skill

Purely cosmetic work (fixing a typo in a doc, whitespace) needs no domain skill. But
**anything substantive invokes at least one domain skill plus `python-craft`,
`complexity-and-srp`, and `testing-discipline`.** There is no "this is too small"
exception for the sync invariant, an LLM call, a bot handler, or a config field.

## 1. Read these files before writing code

In this order:
1. This file (`CLAUDE.md`).
2. The skills that apply to your task (per §0).
3. `CONTRIBUTING.md` — the prose companion to the skills.
4. `README.md` — what the product is and its known limits.

You may skim, but you must have actually read these before changing anything
substantive. Don't rely on summaries inferred from file names.

## 2. Project identity

- **Name:** Subly. Python package: `subtrans`.
- **Goal:** Take a video/audio file → transcribe speech **with timestamps** →
  translate with an LLM → produce an **SRT**. Exposed as a **Telegram bot** (`bot.py`)
  and a **CLI** (`cli.py`). Optional: burn subtitles into the video.
- **Pipeline:** `audio (ffmpeg)` → `transcribe (Whisper)` → `translate (LLM)` →
  `srt` → optional `video (ffmpeg burn/mux)`.
- **Stack:** Python 3.10+, `faster-whisper` (local) or OpenAI Whisper API, any
  OpenAI-compatible LLM endpoint, `python-telegram-bot` v21+, `ffmpeg` on PATH.
- **Design promise:** swap transcription and translation backends **via `.env`, no
  code changes.** Don't break that.

## 3. Code rules — owned by the skills

Every code rule is **canonical in its skill** and is loaded by the §0 gate the moment
you touch the file. This file does not restate them — **invoke the skill.** Map:

| Domain | Skill |
| --- | --- |
| Pipeline structure & the **sync invariant** | `subtitle-pipeline` |
| Model calls, client config, the prompt/parser | `llm-translation` |
| Bot handlers, async, error-to-user, temp cleanup | `telegram-bot` |
| Configuration & secrets | `config-and-secrets` |
| Naming, comments, docstrings, type hints | `python-craft` |
| Single responsibility, size & complexity budgets | `complexity-and-srp` |
| Tests | `testing-discipline` |

**One cross-cutting rule that spans skills:** library stages **raise** (`RuntimeError`
with a clear message); entry points decide how to present it; **never swallow
exceptions silently** (the only tolerated bare `except`s are the two already commented
in the code); use `logging`, never `print()`.

## 4. Hard rules — process

### 4.1 TDD is the workflow

For every code change: write a failing test that encodes the goal → confirm it fails
for the right reason → implement the minimum to pass → keep it green → run `pytest`
before commit. "I'll add tests later" is a process violation. Owned by
`testing-discipline`.

### 4.2 Granular commits

**One logical change per commit.** Imperative subject ≤ 72 chars. Body explains WHY.
Never `git add .` blindly — stage deliberately and review every line. A commit that
mixes a fix + a feature + a rename is three commits.

### 4.3 Branches & PRs

Branch off `main`, PR back to `main` — no direct push. A PR description includes: what
changed and why, the skills invoked (§0), and the test plan. `pytest` must be green
before merge.

### 4.4 No hidden cleanup

Change **only what the task requires.** Don't refactor adjacent code, reformat
unrelated files, or rename in passing. Don't delete pre-existing dead code you didn't
introduce — flag it in the PR instead.

### 4.5 Keep the docs in lockstep

A config change updates `.env.example`. A behavior change updates `README.md`. A new
pattern updates the relevant `SKILL.md` (and `CONTRIBUTING.md`) in the same PR.

## 5. Hard rules — what NOT to build

Out of scope unless the user explicitly approves:
- **TTS / dubbing / audio generation** — Subly produces subtitles, full stop.
- **Anything that breaks the sync invariant** — no merging, splitting, reordering, or
  dropping of **lines**; the line count, order, and timestamps are sacred.
  (Redistributing one sentence's words across its own lines for natural word order is
  allowed — it keeps the count and order — and is owned by `subtitle-pipeline` +
  `llm-translation`.)
- **Strict `json_schema` / Pydantic `.parse()` translation** that drops support for
  non-OpenAI endpoints — portability is a product promise.
- **A web UI or a database** — the surface is a Telegram bot and a CLI; per-chat state
  lives in `chat_data` for the session. Don't add persistence without a clear need.
- **Heavy deps imported at module top** — keep imports lazy (see `subtitle-pipeline`).
- **Bypassing `Config` for configuration**, or hardcoding a token/model/limit.

## 6. Tooling

- **Python:** 3.10+. **System dep:** `ffmpeg` (+ `ffprobe`) on PATH.
- **Runtime deps:** `requirements.txt`. **Dev/test deps:** `requirements-dev.txt`
  (`-r requirements.txt` + `pytest`). Keep runtime lean.
- **Test:** `pytest` (config in `pyproject.toml`). The suite runs with **no network,
  no API key, and without `openai`/`telegram`/`faster_whisper` installed.**
- **Config:** `.env` (git-ignored) from `.env.example`. Loaded by `python-dotenv`.
- **Secrets:** `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY` — never committed or logged.

## 7. When in doubt

When the task is ambiguous, the architecture seems wrong for the request, or you're
tempted to deviate: **stop, surface the question, and wait.** Templates:
- "The task implies merging short lines, but the `subtitle-pipeline` invariant forbids
  changing the segment count. Which is correct?"
- "This needs an `except Exception:` around an SDK that swallows its typed errors.
  The `llm-translation` skill forbids that. Should I narrow it or wrap the SDK in
  `translate.py`?"

The cost of pausing to ask is low. A silent deviation that ships is much higher.

## 8. Skills — quick reference

All seven live in `.claude/skills/`. Invocation rules are in §0.

| Skill | Domain |
| --- | --- |
| [`subtitle-pipeline`](.claude/skills/subtitle-pipeline/SKILL.md) | Stage purity + the sync invariant (id-stability, never-shorter, timestamps from `Segment`). |
| [`llm-translation`](.claude/skills/llm-translation/SKILL.md) | OpenAI-compatible client config, endpoint portability, the prompt/parser contract. |
| [`telegram-bot`](.claude/skills/telegram-bot/SKILL.md) | Thin async handlers, `to_thread`, central error handler, no leaked errors, temp cleanup. |
| [`config-and-secrets`](.claude/skills/config-and-secrets/SKILL.md) | `Config.from_env`, `.env.example` lockstep, no secret logging/commit. |
| [`testing-discipline`](.claude/skills/testing-discipline/SKILL.md) | pytest, pure logic, mock the IO seam, no network/heavy deps, invariant tests. |
| [`python-craft`](.claude/skills/python-craft/SKILL.md) | Naming, function/class design, type hints, comments, docstrings. |
| [`complexity-and-srp`](.claude/skills/complexity-and-srp/SKILL.md) | Single responsibility, size/complexity budgets, cohesion, no over-engineering. |
