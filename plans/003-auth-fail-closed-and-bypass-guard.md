# Plan 003: Reject session cookies signed with an empty secret, and stop bearer tokens from enabling the dev auth bypass

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 69adcfa..HEAD -- src/finance/auth_session.py src/api/auth.py src/api/routers/auth.py src/api/routers/config.py tests/unit/test_auth_session.py tests/unit/test_api_auth_middleware.py tests/unit/test_api_auth_endpoints.py`
> If any of these files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before you start. If
> they don't match, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `69adcfa`, 2026-09-23

## Why this matters

Tidings has three auth channels: bearer tokens for agents, a signed session
cookie for browsers, and TOFU (open until a password is set). Two gaps let a
caller get more access than intended.

1. **Empty signing secret is accepted.** Both cookie verifiers read the
   secret with `cfg.get("session_signing_secret") or ""`. The secret is only
   created lazily when a cookie is first issued. If a password is set but the
   secret key is missing, any cookie HMAC-signed with an empty key verifies,
   and the cookie format is public in the source. A missing secret can come
   from a hand-rotated config (the docs tell operators to rotate it), a
   restored config, or a failed write between setting the password and
   issuing the first cookie. In that state, anyone who can reach the port can
   log in without the password.
2. **A bearer token can switch off auth for everyone.** `PUT /api/v1/config`
   accepts `auth_bypass_for_dev` and writes it without checking who is
   calling. Any `read+write` agent token can set it to `true`. From then on,
   every anonymous request is served with full access, and that persists
   after the token is revoked. The flag is meant to be flipped by the
   operator in Settings → Password, which is a browser session.

These are decided behaviours that stay unchanged: TOFU (no password → open)
and the bypass flag itself are intentional (`docs/guides/configuration.md`,
`auth_bypass_for_dev`). This plan does not change them. It closes the
empty-key hole and restricts *who* can turn the bypass on.

## Current state

- `src/finance/auth_session.py:71-86`, `verify_session(token, secret)`: HMAC-SHA256 verify, constant-time compare. It does not reject an empty `secret`.

  ```python
  def verify_session(token: str, secret: str) -> SessionPayload | None:
      """Constant-time HMAC verify. Returns the payload or None if invalid or expired.
      ...
      """
      if not token or "." not in token:
          return None
      payload_b64, sig_b64 = token.split(".", 1)
      expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), sha256).digest()
  ```

- `src/api/auth.py:160-167`, the cookie channel in `authenticate_request`:

  ```python
      cookie_value = request.cookies.get(COOKIE_NAME)
      if cookie_value:
          secret = cfg.get("session_signing_secret") or ""
          version = int(cfg.get("session_version", 0) or 0)
          payload = verify_session(cookie_value, secret)
  ```

- `src/api/routers/auth.py:70-78`, `_has_valid_session`: the same `or ""`
  pattern. It gates `POST /api/v1/auth/sign-out-all`.
- `src/api/auth.py:54-67`: `Principal.kind` is one of
  `"token" | "session" | "tofu" | "dev-bypass"`. The middleware sets
  `request.state.principal` for every authenticated `/api/v1/*` request
  (`src/api/auth.py`, `bearer_auth_middleware`).
- `src/api/routers/config.py:55-86`, `put_config(body: AppConfigUpdateRequest)`:
  builds `updates` from the fields the client sent, validates `timezone`,
  then calls `update_config(updates)`. It never looks at the principal.

  ```python
  async def put_config(body: AppConfigUpdateRequest):
      old_cfg = get_config()
      ...
      sent = body.model_dump(exclude_unset=True)
      updates = cast(
          "AppConfig",
          {k: v for k, v in sent.items() if v is not None or k in NULLABLE_CONFIG_KEYS},
      )

      if "timezone" in updates:
          ...
  ```

- `src/api/models/config.py:89`: `auth_bypass_for_dev: bool | None = None` in `AppConfigUpdateRequest`.
- `frontend/src/components/settings/AccessSection.tsx:273-300`: the only UI
  that flips the flag. It runs in the browser, so the caller is a `session`
  principal, or `tofu` before a password exists.
- `src/api/errors.py`: `ApiException(status, code, message)` gives the
  unified `{error, code, details}` body. The 403 code used elsewhere is `"FORBIDDEN"`.

Test patterns to copy (`tests/unit/test_api_auth_middleware.py`):

- The `isolated_config` fixture (line 28) points config at a tmp file.
- `_seed_password()` (line 47) leaves TOFU mode.
  `agent_tokens.add_token(label=..., scope="read+write")` returns `(record, raw)`.
- `client = api_client_factory(create_app())`, then call the app with
  `headers={"Authorization": f"Bearer {raw}"}` or
  `client.cookies.set(COOKIE_NAME, cookie)`.
- Assertions use `assert_ok(resp)` and `assert_problem(resp, status, code)` from `tests/asserts.py`.
- `TestCookieSession` (line 257) and `TestDevBypass` (line 335) are the nearest exemplars.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Deps | `uv sync` | exit 0 |
| Targeted tests | `uv run pytest tests/unit/test_auth_session.py tests/unit/test_api_auth_middleware.py tests/unit/test_api_auth_endpoints.py tests/unit/test_api_config.py -q` | all pass |
| Full backend tests | `uv run pytest tests/ -m "not integration" -q -n 8` | all pass |
| Lint / format / types | `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/` | exit 0 |
| Test conventions ratchet | `uv run python scripts/checks/check_test_conventions.py` | exit 0 |
| OpenAPI drift | `make verify-openapi` | exit 0 (this plan must not change the schema) |

## Scope

**In scope**:

- `src/finance/auth_session.py`: `verify_session` only
- `src/api/routers/config.py`: `put_config` only
- `tests/unit/test_auth_session.py`, `tests/unit/test_api_auth_middleware.py`, `tests/unit/test_api_auth_endpoints.py`: new tests
- `docs/guides/configuration.md`: one sentence on the `auth_bypass_for_dev` row
- `CHANGELOG.md`: one `### Security` bullet

**Out of scope** (do NOT touch):

- `src/api/auth.py` and `src/api/routers/auth.py`. Once `verify_session`
  rejects an empty secret, both `or ""` call sites fail closed without
  edits. Leave them as they are, so the fix lives in one place.
- The TOFU channel and the bypass semantics in `authenticate_request`.
- Login rate limiting, CORS and host binding. These are separate findings,
  listed in `plans/README.md`.
- Any other `AppConfigUpdateRequest` field. Restrict only `auth_bypass_for_dev` in this plan.
- `frontend/`: no UI change is needed. The Settings toggle runs as a session principal.

## Git workflow

- Commit on the current branch. Don't create branches (root `CLAUDE.md` §Committing).
- Use the `/commit` skill if available. Otherwise use the house format, for example
  `🔒 security(auth): Fail closed on an empty session secret`.
- One commit per step group is fine: Steps 1–2 as one commit, Steps 3–4 as another. Stage by name. Do not push unless told to.

## Steps

### Step 1: Write the failing tests for the empty secret first

1. `tests/unit/test_auth_session.py`: add
   `test_empty_secret_never_verifies`. Build a token with
   `issue_session(version=0, secret="")`, and assert
   `verify_session(token, "") is None`. Check the file's imports and add
   `issue_session` if it is missing.
2. `tests/unit/test_api_auth_middleware.py::TestCookieSession`: add
   `test_cookie_signed_with_empty_secret_is_rejected_when_secret_missing`.
   Call `_seed_password()`. Do **not** call `get_session_signing_secret()`,
   so the config has no secret. Set a cookie from
   `issue_session(version=0, secret="")`, `GET /api/v1/categories`, and
   `assert_problem(resp, 401)`.
3. `tests/unit/test_api_auth_endpoints.py::TestSignOutAll`: add a test in
   the same spirit. Set the password with no secret, send the empty-secret
   cookie, POST `/api/v1/auth/sign-out-all` with no body, and expect
   `assert_problem(resp, 401)`. Read that file's fixtures first. It uses a
   `client` fixture, and its setup may create a secret. If so, remove the
   `session_signing_secret` key with `app_config.update_config` or by
   rewriting the tmp config, matching how the file already manipulates config.

**Verify**: run the three test files. The **new tests fail**: the first asserts `None` but gets a payload, and the others get 200. That confirms the hole.

### Step 2: Fail closed in `verify_session`

At the top of `verify_session` in `src/finance/auth_session.py`, add:

```python
    if not secret:
        # An empty key makes the HMAC forgeable by anyone who knows the cookie
        # format; a missing secret must never authenticate a session.
        return None
```

Mention in the docstring that an empty secret always fails.

**Verify**: `uv run pytest tests/unit/test_auth_session.py tests/unit/test_api_auth_middleware.py tests/unit/test_api_auth_endpoints.py -q` → all pass, including the 3 new tests.

### Step 3: Write the failing tests for the bypass guard

Add a new class `TestAuthBypassToggleGuard` to
`tests/unit/test_api_auth_middleware.py`, after `TestDevBypass`:

1. `test_read_write_token_cannot_enable_bypass`: `_seed_password()`; add a
   `read+write` token; PUT `/api/v1/config` with `{"auth_bypass_for_dev": true}`
   and the bearer header. Expect `assert_problem(resp, 403, "FORBIDDEN")` and
   `app_config.get_config().get("auth_bypass_for_dev")` still falsy. Call
   `app_config.invalidate_config_cache()` before reading if needed.
2. `test_read_write_token_can_disable_bypass`: seed the password and
   `update_config({"auth_bypass_for_dev": True})`. The token PUTs `false` →
   `assert_ok`, and the flag is now `False`. Turning protection back on must
   never be blocked.
3. `test_session_can_enable_bypass`: seed the password, then build a valid
   cookie exactly as `TestCookieSession.test_valid_cookie_allows_request`
   does. PUT `true` → `assert_ok`, and the flag is `True`.
4. `test_tofu_can_enable_bypass`: no password. PUT `true` with no credentials → `assert_ok`.
5. `test_token_put_without_bypass_field_unaffected`: a `read+write` token
   PUTs `{"timezone": "America/Toronto"}` → `assert_ok`.

**Verify**: run the class. Tests 1 fails (it gets 200) and the other four pass.

### Step 4: Guard the field in `put_config`

In `src/api/routers/config.py`:

1. Add `request: Request` to `put_config`'s parameters. Import `Request` from
   `fastapi` if it is not already imported. FastAPI injects it, and it does
   not change the OpenAPI schema.
2. Right after `updates` is built, before the `timezone` check, add:

   ```python
       # Only the operator (browser session, or TOFU before a password exists)
       # may turn the dev auth bypass ON. A bearer token enabling it would open
       # the API to every anonymous caller and outlive the token's revocation.
       # Turning it OFF is always allowed.
       if updates.get("auth_bypass_for_dev") is True and not old_cfg.get("auth_bypass_for_dev"):
           principal = getattr(request.state, "principal", None)
           if principal is None or principal.kind not in ("session", "tofu"):
               raise ApiException(403, "FORBIDDEN", "only a signed-in browser session can enable auth_bypass_for_dev")
   ```

   The `principal is None` branch fails closed if the route is ever reached
   without the middleware.

**Verify**: `uv run pytest tests/unit/test_api_auth_middleware.py tests/unit/test_api_config.py -q` → all pass. Then `make verify-openapi` → exit 0, with no schema drift.

### Step 5: Docs, changelog, full gate

- `docs/guides/configuration.md`, on the `auth_bypass_for_dev` row
  (≈line 45): append "Only a signed-in browser session can turn it on. Agent
  tokens get a 403."
- `CHANGELOG.md` → `## [Unreleased]` → `### Security`: one bullet covering
  both fixes. Sessions now fail closed when the signing secret is missing,
  and agent tokens can no longer enable the dev auth bypass.

**Verify**: `uv run pytest tests/ -m "not integration" -q -n 8` → 0 failures. `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run python scripts/checks/check_test_conventions.py && uv run python scripts/checks/check_changelog.py` → exit 0.

## Test plan

- New tests: 3 for the empty secret (unit, middleware, sign-out-all) and 5 for the bypass guard.
- Each new negative test is shown failing before its fix, in Steps 1 and 3.
- Regression: the full auth and config suites, plus `make verify-openapi`.

## Done criteria

- [ ] `grep -n "if not secret" src/finance/auth_session.py` → 1 match
- [ ] `grep -n "auth_bypass_for_dev" src/api/routers/config.py` → at least 1 match
- [ ] `uv run pytest tests/ -m "not integration" -q -n 8` → 0 failures, with 8 new tests present
- [ ] `make verify-openapi` → exit 0
- [ ] Lint, format, pyright and test-conventions → exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` row 003 set to DONE

## STOP conditions

- An existing test calls `verify_session` or builds a cookie with an empty
  secret and expects success. Report it. Don't weaken the check.
- `request.state.principal` is not set for `/api/v1/config` in the test app,
  so test 3 or 4 of Step 3 fails with a 403. That means the middleware
  wiring differs from this plan's assumption.
- `make verify-openapi` shows drift after Step 4.
- The frontend's Settings toggle turns out to call the API with a bearer
  token rather than the cookie. Search `frontend/src/lib/api.ts` for
  `Authorization`. If it does, the guard would break the UI. Stop and report.

## Maintenance notes

- If a new security-sensitive config key is added (for example
  `storage`, `s3_backup_*`, or anything that widens exposure), extend the same
  guard. A follow-up could turn this into a declarative
  `OPERATOR_ONLY_KEYS` set. It's deferred because only one key needs it today.
- Consider a startup warning, like `_warn_if_auth_bypass_exposed` in
  `src/api/main.py`, when `app_password_hash` is set but
  `session_signing_secret` is missing. It's deferred because this fix already
  fails closed.
- Reviewers: confirm that disabling the bypass is never blocked, and that the
  403 uses the unified error shape.
