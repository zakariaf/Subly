---
name: config-and-secrets
description: Use BEFORE adding a setting, reading an environment variable, or handling a token/API key. Owns the rule that all configuration flows through Config.from_env(), every setting is documented in .env.example, and secrets are never logged or committed.
---

# Skill: config-and-secrets

One typed config object, one `.env.example`, zero secrets in code or logs.
Source: `CONTRIBUTING.md` → "Configuration & secrets".

## When to invoke

Invoke this skill before:
- Adding or changing a field on `Config` (`subtrans/config.py`).
- Reading any environment variable.
- Introducing a new tunable value (timeout, model name, limit, default).
- Touching anything that holds a token or API key.

## Hard rules

1. **All configuration lives in `Config` and is read via `Config.from_env()`.** No
   tunable value is hardcoded mid-code. If a number or endpoint might ever need to
   change per environment, it's a `Config` field.

2. **Never `os.environ.get(...)` in business code.** The only place that reads the
   environment is `config.py`'s `from_env()` (via the `_get` helper). Everything
   else takes a `cfg` and reads `cfg.<field>`.

3. **Every new setting gets three things, together, in one change:**
   - a typed field on `Config` with a sensible default,
   - a line in `from_env()` parsing it (with type coercion: `int(...)`, `float(...)`),
   - an entry in `.env.example` **with a comment** explaining it.
   A setting missing any of the three is incomplete.

4. **Defaults make the app run.** `Config()` with no env set must produce a usable
   local config (e.g. `transcribe_backend="local"`). Only the two real secrets
   (`TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`) are blank by default.

5. **Secrets are never logged, never serialized into errors, never committed.**
   `.env` is git-ignored; `.env.example` holds the keys with blank values. Don't
   log `cfg.openai_api_key` or include it in an exception message.

6. **Values are stripped.** `_get` trims whitespace; rely on it rather than
   re-trimming at call sites.

## The shape

```python
# config.py — field, parse, default. All three in one place.
@dataclass
class Config:
    request_timeout: float = 60.0         # 1. typed field + default
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            request_timeout=float(_get("REQUEST_TIMEOUT", "60")),  # 2. parse + coerce
            max_retries=int(_get("MAX_RETRIES", "2")),
        )
```

```dotenv
# .env.example — 3. documented, blank for secrets only
# Per-request timeout (seconds) and automatic retries for transient errors.
REQUEST_TIMEOUT=60
MAX_RETRIES=2
```

## Anti-patterns to flag

- ✗ `os.environ.get(...)` or `os.getenv(...)` anywhere outside `config.py`.
- ✗ A magic number / URL / model name inline in `translate.py`, `bot.py`, etc.
- ✗ A new `Config` field with no matching `.env.example` entry (or vice versa).
- ✗ A required env var with no default that crashes `Config()` in tests.
- ✗ Logging or string-formatting a token / API key into a message.
- ✗ Committing a real `.env`, or putting real secret values in `.env.example`.
- ✗ Re-stripping a value that `_get` already stripped.

## Why these rules

A single typed config means the app fails fast and obviously when misconfigured,
tests can build a `Config()` with no environment, and there's exactly one file to
read to know what's tunable. Keeping `.env.example` in lockstep is what makes
`cp .env.example .env` a working setup step instead of a scavenger hunt. And
secrets stay out of logs and git because the one place that reads them is the one
place that knows they're secret.
