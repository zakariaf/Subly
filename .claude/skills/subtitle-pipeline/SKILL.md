---
name: subtitle-pipeline
description: Use BEFORE writing or modifying any pipeline stage in subtrans/ (audio, transcribe, translate, srt, video) or the glue in pipeline.py. Owns stage purity and the one load-bearing domain rule — subtitles must never desync from their timestamps.
---

# Skill: subtitle-pipeline

The pipeline is a chain of independent stages, and the output SRT must always line
up with the audio. Source: `CONTRIBUTING.md` → "Project layout", "Python style",
"The subtitle-sync invariant".

## When to invoke

Invoke this skill before:
- Adding or editing a stage module in `subtrans/` (`audio.py`, `transcribe.py`, `translate.py`, `srt.py`, `video.py`).
- Changing `pipeline.py` or how stages are wired together.
- Any code that creates, transforms, filters, reorders, or counts `Segment`s.
- Changing timestamp formatting or SRT block assembly.

## Hard rules

1. **One stage = one module = one responsibility.** `audio` extracts, `transcribe`
   transcribes, `translate` translates, `srt` assembles, `video` attaches. A stage
   that "needs" to do two things is two stages.

2. **Orchestration is not a stage.** Wiring stages together lives in `pipeline.py`
   or the entry points (`bot.py`, `cli.py`). A stage never calls another stage.

3. **Stages are pure where they can be.** `srt.py` and the parsing in `translate.py`
   take data in and return data out — no globals, no hidden state. The only stages
   that touch the outside world are `audio`/`video` (ffmpeg) and the network call in
   `transcribe`/`translate`.

4. **No import-time side effects.** Heavy/optional deps (`faster_whisper`, `openai`)
   are imported *inside* the function that needs them, never at module top. This
   keeps imports fast and lets tests run without every library installed. Keep it
   that way.

5. **THE INVARIANT — the SRT is never shorter than the transcript, and order is
   preserved.** Subtitles desync the instant a step merges, splits, reorders, or
   drops a line relative to the timestamps. So:
   - Every segment carries a **stable integer id** (its index).
   - Any transform that "improves" text (translation, cleanup) must return **one
     output per input id, in the same order**.
   - Missing/failed outputs **fall back to the original text** — never to nothing.
   See `translate.translate_segments`'s final line.

6. **Timestamps come from `Segment`, never from the model.** `start`/`end` are set
   by the transcriber and are sacred. The translator only ever changes `text`.

7. **`format_timestamp` clamps and rounds defensively.** Negative → `0`, milliseconds
   rounded. Don't hand-format timestamps elsewhere; call `srt.format_timestamp`.

## The shape

```python
# The invariant, enforced at the seam between translate and srt:
# translate_segments returns exactly len(segments) strings, in order, with
# originals filling any gap the model left.
return [translations.get(i) or segments[i].text for i in range(len(segments))]
```

```python
# A stage: pure-ish, single responsibility, heavy import is lazy.
def _get_local_model(model_size, device, compute_type):
    from faster_whisper import WhisperModel   # imported here, not at module top
    ...
```

## Anti-patterns to flag

- ✗ A stage importing and calling another stage directly (bypassing `pipeline.py`).
- ✗ `import faster_whisper` or `from openai import OpenAI` at module top level.
- ✗ A transform that returns fewer items than it received, or reorders them.
- ✗ Dropping a segment because its translation was empty (must fall back to original).
- ✗ The model being trusted to produce timestamps, or recomputing `start`/`end`.
- ✗ Formatting an SRT timestamp by hand instead of `format_timestamp`.
- ✗ A stage that does two jobs (e.g. transcribe *and* translate in one function).
- ✗ Module-level globals that hold per-job state.

## Why these rules

The whole product is "subtitles that stay in sync." Every other feature is
worthless if a line drifts. Stable ids + originals-as-fallback is the cheap,
robust way to guarantee it: the model gets context to translate well, but it
*cannot* break the line-to-timestamp mapping no matter how it misbehaves. Keeping
stages independent and import-light is what lets us test that guarantee fast,
without ffmpeg or an API key.
