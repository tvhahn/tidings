# Plan 002: Verify the IMAP server's TLS certificate before sending the mailbox password

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 69adcfa..HEAD -- src/finance/imap_poller.py tests/unit/test_imap_poller.py docker-compose.yml .env.example docs/guides/self-hosted-email-setup.md`
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

The self-hosted IMAP poller opens its connection with
`imaplib.IMAP4_SSL(server, port, timeout=...)` and passes no `ssl_context`.
In CPython 3.12, `IMAP4_SSL` then falls back to `ssl._create_stdlib_context()`.
That function is the same object as `ssl._create_unverified_context`, so the
server certificate and hostname are **never checked**.

The poller then calls `login()` over that connection with the mailbox's app
password. Anyone who can intercept the network path can therefore pose as the
IMAP server. They could capture the credential, and feed forged "bank alert"
emails into the ledger.

The fix passes a verifying context. It also adds an optional CA-bundle
setting for self-hosters whose IMAP server uses a private CA.

## Current state

- `src/finance/imap_poller.py`: the long-running poller sidecar (`python -m src.finance.imap_poller`).
  - Lines 112–125, `ImapPoller.connect()`:

    ```python
    def connect(self):
        """Connect to the IMAP server, or verify the existing connection is alive via NOOP."""
        if self._mail is not None:
            ...
        password = self._password.replace(" ", "")  # Google App Passwords have spaces
        self._mail = imaplib.IMAP4_SSL(self._server, self._port, timeout=_SOCKET_TIMEOUT)
        self._mail.login(self._user, password)
        self._mail.select(self._folder)
    ```

  - Lines 83–110, `ImapPoller.__init__`: positional `server, port, user,
    password, folder, poll_interval`, followed by keyword-only arguments after
    `*` (`transactions_db`, `context_enricher`, `api_client`,
    `parse_failure_store`, `db_path`).
  - Lines 292–304, `main()`: reads `IMAP_SERVER`, `IMAP_PORT`, `IMAP_USER`,
    `IMAP_PASSWORD`, `IMAP_FOLDER` and `IMAP_POLL_INTERVAL` with `os.environ.get`,
    then constructs `ImapPoller(...)` further down.
- `tests/unit/test_imap_poller.py:669-720`, `TestConnectionManagement`: the
  pattern for connect tests. They patch
  `src.finance.imap_poller.imaplib.IMAP4_SSL` and build the poller with
  `_make_poller()`.
- `docker-compose.yml`: the `imap-poller` service's `environment:` list,
  lines 22–29, passes `IMAP_*` variables through with `${VAR:-default}`.
- `.env.example:53-60`: the commented `IMAP_*` block.
- `docs/guides/self-hosted-email-setup.md:216-233`: the env var listing and
  the "Defaults baked in" paragraph.

Confirmed at planning time, using the project venv:

```
uv run python -c "import ssl; print(ssl._create_stdlib_context is ssl._create_unverified_context)"
True
```

Conventions:

- Environment variables are read in `main()` only. The class receives plain
  values, so tests never touch `os.environ`.
- Logging goes through `logger = logging.getLogger(__name__)`. Never log the
  password or the full username. `_mask_user` exists for the username.
- Docs voice: sentence case, no exclamation marks (`docs/brand/voice.md`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Deps | `uv sync` | exit 0 |
| Targeted tests | `uv run pytest tests/unit/test_imap_poller.py tests/unit/test_imap_poller_idle.py -q` | all pass |
| Full backend tests | `uv run pytest tests/ -m "not integration" -q -n 8` | all pass |
| Lint / format / types | `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/` | exit 0, `0 errors` |
| Canon links | `uv run python scripts/checks/check_canon_links.py` | exit 0 |

## Scope

**In scope**:

- `src/finance/imap_poller.py`
- `tests/unit/test_imap_poller.py`
- `docker-compose.yml`: add one env line to the `imap-poller` service only
- `.env.example`: add one commented line to the IMAP block
- `docs/guides/self-hosted-email-setup.md`: document the new optional variable
- `CHANGELOG.md`: one `### Security` bullet under `## [Unreleased]`

**Out of scope** (do NOT touch):

- `tests/integration/test_imap_poller.py`: an integration test against a real server, marked `integration`.
- `src/finance/poller_state.py`, `src/finance/email_pipeline.py`: unrelated to transport security.
- Any option to *disable* verification. Do not add `IMAP_INSECURE` or anything like it.
- Mounting a CA file into the container. That's the operator's choice, via a compose override.

## Git workflow

- Commit on the current branch. Don't create branches (root `CLAUDE.md` §Committing).
- Use the `/commit` skill if available. Otherwise use the house format, for example
  `🔒 security(imap): Verify the IMAP server certificate before login`.
- Stage files by name. Do not push unless told to.

## Steps

### Step 1: Build a verifying SSL context

In `src/finance/imap_poller.py`:

1. Add `import ssl` in the stdlib import block, keeping it alphabetical.
2. Add a module-level helper under `_mask_user`:

   ```python
   def _build_ssl_context(ca_file: str | None = None) -> ssl.SSLContext:
       """Certificate- and hostname-verifying TLS context for the IMAP connection.

       imaplib.IMAP4_SSL without an explicit context uses the stdlib's
       *unverified* context, so the server certificate is never checked. Pass
       ``ca_file`` to trust a private CA (self-hosted mail servers).
       """
       return ssl.create_default_context(cafile=ca_file or None)
   ```

3. Add a keyword-only parameter `ca_file: str | None = None` to
   `ImapPoller.__init__`, after `db_path`. Store it as `self._ca_file`.
4. In `connect()`, pass the context:

   ```python
   self._mail = imaplib.IMAP4_SSL(
       self._server,
       self._port,
       ssl_context=_build_ssl_context(self._ca_file),
       timeout=_SOCKET_TIMEOUT,
   )
   ```

**Verify**: `uv run pytest tests/unit/test_imap_poller.py tests/unit/test_imap_poller_idle.py -q` → all pass. The existing tests patch `IMAP4_SSL`, so the new kwarg is accepted.

### Step 2: Read `IMAP_CA_FILE` in `main()`

Next to the other `os.environ.get` calls in `main()`, add
`ca_file = os.environ.get("IMAP_CA_FILE", "").strip() or None` and pass
`ca_file=ca_file` where `main()` constructs `ImapPoller(...)`.

If `ca_file` is set but `Path(ca_file).is_file()` is false, log an error that
names the variable (the path is fine to log) and `sys.exit(1)`. A
misconfigured CA should fail at startup, not on every reconnect.

**Verify**: `uv run pyright src/` → `0 errors`.

### Step 3: Tests

Add these to `TestConnectionManagement` in `tests/unit/test_imap_poller.py`,
matching the style of `test_connect_strips_password_spaces`:

1. `test_connect_passes_verifying_ssl_context`: patch `IMAP4_SSL` and call
   `connect()`. Take the `ssl_context` kwarg from `mock_imap_cls.call_args.kwargs`
   and assert `ctx.verify_mode == ssl.CERT_REQUIRED` and `ctx.check_hostname is True`.
2. `test_build_ssl_context_with_ca_file_loads_it`: patch
   `src.finance.imap_poller.ssl.create_default_context` and call
   `_build_ssl_context("/tmp/ca.pem")`. Assert the patched function was called
   once with `cafile="/tmp/ca.pem"`. Name the mock
   (`mock.name = "create_default_context"`), per `tests/CLAUDE.md`.
3. `test_build_ssl_context_default_uses_system_trust`: call
   `_build_ssl_context()` with no patching. Assert `verify_mode == ssl.CERT_REQUIRED`
   and `check_hostname is True`.

**Verify**: `uv run pytest tests/unit/test_imap_poller.py -q` → all pass, including 3 new tests.

### Step 4: Config surface and docs

- `docker-compose.yml`, `imap-poller` → `environment:`: add
  `- IMAP_CA_FILE=${IMAP_CA_FILE:-}` after the `IMAP_POLL_INTERVAL` line.
- `.env.example`: add
  `# IMAP_CA_FILE=/app/data/imap-ca.pem   # optional: trust a private CA for a self-hosted IMAP server`
  after `# IMAP_POLL_INTERVAL=60`.
- `docs/guides/self-hosted-email-setup.md`: after the "Defaults baked in"
  paragraph (≈line 230), add a short paragraph. It should say that the poller
  verifies the server's TLS certificate. Gmail and other public providers
  need no setup. A self-hosted mail server with a private CA can set
  `IMAP_CA_FILE` to a PEM bundle path that is visible inside the container,
  for example a file placed in the `finance_data` volume under `/app/data/`.
  Sentence case, no exclamation marks.

**Verify**: `uv run python scripts/checks/check_canon_links.py` → exit 0. `docker compose config -q` → exit 0, if Docker is available. Skip it if not, and say so in your report.

### Step 5: Changelog and commit

Add under `## [Unreleased]` → `### Security`:
"The IMAP poller now verifies the mail server's TLS certificate and hostname before sending the app password. Self-hosted mail servers with a private CA can set `IMAP_CA_FILE`."
Also recommend, in the same bullet, that anyone who ran the poller on an
untrusted network rotate their IMAP app password.

**Verify**: `uv run python scripts/checks/check_changelog.py` → exit 0. Then commit.

## Test plan

- 3 new unit tests (Step 3). They cover the verifying context on connect,
  CA file passthrough, and the default being verified.
- Regression: the whole `test_imap_poller.py` and `test_imap_poller_idle.py` files.
- Full gate: `uv run pytest tests/ -m "not integration" -q -n 8`.

## Done criteria

- [ ] `grep -n "ssl_context=_build_ssl_context" src/finance/imap_poller.py` → 1 match
- [ ] `grep -rn "IMAP4_SSL(" src/ | grep -v ssl_context` → no output
- [ ] `grep -n "IMAP_CA_FILE" docker-compose.yml .env.example docs/guides/self-hosted-email-setup.md src/finance/imap_poller.py` → at least one match in each file
- [ ] `uv run pytest tests/ -m "not integration" -q -n 8` → 0 failures
- [ ] `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/` → exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` row 002 set to DONE

## STOP conditions

- `connect()` or `main()` no longer looks like the excerpts above, for
  example because the poller moved to a different IMAP library.
- Another module constructs `imaplib.IMAP4_SSL` or `IMAP4` directly. Check
  with `grep -rn "IMAP4" src/`. Report it rather than widening scope.
- An existing test asserts the exact `IMAP4_SSL` call arguments and fails for
  a reason other than the new kwarg.

## Maintenance notes

- If STARTTLS on port 143 support is ever added, it must pass the same
  context to `starttls(ssl_context=...)`. The stdlib default there is
  unverified too.
- Reviewers: confirm no code path can construct the connection without a
  context, and that nothing logs the CA path contents or the password.
- Deferred: SMTP/POP clients don't exist today, so there's nothing to fix.
  Any future stdlib mail client has the same default and needs the same
  treatment.
