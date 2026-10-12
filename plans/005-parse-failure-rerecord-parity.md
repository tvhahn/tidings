# Plan 005: Make re-recording a parse failure keep its review status on DynamoDB, matching SQLite

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`, unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 69adcfa..HEAD -- src/finance/parse_failure_store.py src/finance/parse_failure_store_local.py src/finance/parse_failure_store_base.py tests/unit/test_parse_failure_store.py`
> If any of these files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before you start. If
> they don't match, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `69adcfa`, 2026-09-23

## Why this matters

Unparseable bank emails are quarantined in a parse-failure store, which the
UI shows as "Needs review". The user can dismiss a row, or the row can be
marked recovered with a link to the transaction that recovered it.

The failure id is derived from the email's content. When the same email
arrives again, `record_failure` is called with the same id. That happens on
a Lambda or IMAP redelivery, or when the user re-uploads the `.eml`. The two
backends handle that re-record differently:

- **SQLite** (`ON CONFLICT(id) DO UPDATE`) updates only `updated_at` and
  `failure_stage`. The status, recovery link, `created_at` and
  `received_at` are kept.
- **DynamoDB** does a full `put_item`. That resets `Status` to the incoming
  value (default `"quarantined"`), wipes `RecoveredDateFileName`, and resets
  `CreatedAt`/`ReceivedAt`.

On the AWS deployment, a failure the user already dismissed or recovered
therefore reappears in "Needs review" on every redelivery, and loses its link
to the recovering transaction.

The repo's rule is that dual-backend pairs must behave identically, and a
contract test must run on both. SQLite's behaviour is the one the docstrings
describe ("upserts the same row"), so DynamoDB is brought into line with it.

## Current state

- `src/finance/parse_failure_store_local.py:104-150`, the SQLite `record_failure`. This is the **reference behaviour**:

  ```python
              conn.execute(
                  """
                  INSERT INTO parse_failures (
                      id, user_id, received_at, from_email, subject, file_name,
                      detected_institution, failure_stage, status,
                      recovered_date_file_name, alert_classifier_result,
                      email_json, created_at, updated_at
                  ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                  ON CONFLICT(id) DO UPDATE SET
                      updated_at = excluded.updated_at,
                      failure_stage = excluded.failure_stage
                  """,
  ```

- `src/finance/parse_failure_store.py:105-140`, the DynamoDB `record_failure`, which diverges:

  ```python
          item: dict[str, Any] = {
              "PK": self.USER_PK,
              "SK": f"FAIL#{sk_token}#{failure_id}",
              "FailureId": failure_id,
              "ReceivedAt": received_at,
              "FromEmail": failure.get("from_email") or email_details.get("from_email"),
              "Subject": failure.get("subject") or email_details.get("subject"),
              "FileName": failure.get("file_name") or email_details.get("file_name"),
              "DetectedInstitution": failure.get("detected_institution"),
              "FailureStage": failure.get("failure_stage", "no_parser_match"),
              "Status": failure.get("status", "quarantined"),
              "RecoveredDateFileName": failure.get("recovered_date_file_name"),
              "AlertClassifierResult": self.coerce_classifier(classifier),
              "EmailJson": email_json,
              "CreatedAt": received_at,
              "UpdatedAt": now,
          }
          # Pruning: SQLite prunes on write; DynamoDB rows are few and cheap —
          # revisit with TTL if needed.
          self.table.put_item(Item=item)
          return failure_id
  ```

  The SK is deterministic for a redelivered email (`_sk_token_for`, lines
  88–103). A redelivery therefore targets the **same item**, which is what
  makes an `update_item` upsert correct.
- `src/finance/parse_failure_store.py:229-264`, `set_status`: the in-file
  exemplar for `update_item`. It uses `ExpressionAttributeNames={"#s": "Status"}`
  because `Status` is a DynamoDB reserved word.
- Callers of `record_failure` are in `src/finance/parse_recovery.py` (lines
  403, 414, 426, 494). The "recovered" path records with
  `"status": "recovered"` and then calls `mark_recovered` → `set_status(...)`.
  Keeping an existing status on re-record is therefore safe, because
  `set_status` still applies the transition afterwards.
- Contract tests: `tests/unit/test_parse_failure_store.py`, class
  `TestParseFailureStoreContract`. Its `store` fixture is parametrized over
  `["dynamodb", "sqlite"]`, with moto for DynamoDB. The helpers are `_email(**overrides)` and
  `_failure(email, **overrides)`. `test_idempotent_re_record_no_duplicate`
  (line 94) is the nearest exemplar. `TestParseFailureStoreLegacyDuplicates`
  (line 260) must keep passing.

Conventions (`src/finance/CLAUDE.md`, `tests/CLAUDE.md`):

- For a dual-backend change, test both backends through the parametrized contract fixture.
- Assert specific values: `got["status"] == "dismissed"`, never `assert got`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Deps | `uv sync` | exit 0 |
| Contract tests | `uv run pytest tests/unit/test_parse_failure_store.py -q` | all pass |
| Related suites | `uv run pytest tests/unit/test_api_parse_failures.py tests/unit/test_parse_recovery.py tests/unit/test_imap_poller.py -q` | all pass. If a file doesn't exist, drop it from the command. |
| Full backend tests | `uv run pytest tests/ -m "not integration" -q -n 8` | all pass |
| Lint / format / types | `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/` | exit 0 |

## Scope

**In scope**:

- `src/finance/parse_failure_store.py`: `record_failure` only
- `src/finance/parse_failure_store_base.py`: docstring of the abstract `record_failure` only
- `tests/unit/test_parse_failure_store.py`: new contract tests
- `CHANGELOG.md`: one `### Fixed` bullet

**Out of scope** (do NOT touch):

- `src/finance/parse_failure_store_local.py`: SQLite is the reference behaviour. Don't change it.
- `src/finance/parse_recovery.py` and the routers.
- DynamoDB pruning/TTL (the comment at the `put_item` site) and the legacy-duplicate read path.

## Git workflow

- Commit on the current branch. Don't create branches (root `CLAUDE.md` §Committing).
- Use the `/commit` skill if available. Otherwise use the house format, for example
  `🐛 fix(parse-failures): Keep review status when DynamoDB re-records an email`.
- Stage by name. Do not push unless told to.

## Steps

### Step 1: Write the contract tests (they fail on DynamoDB only)

Add these to `TestParseFailureStoreContract`:

1. `test_re_record_preserves_dismissed_status`: `fid = store.record_failure(_failure())`;
   `store.set_status(fid, "dismissed")`; then
   `store.record_failure(_failure(failure_stage="no_parser_match"))`.
   Assert `got["status"] == "dismissed"` and
   `got["failure_stage"] == "no_parser_match"`, since the stage *is* updated.
2. `test_re_record_preserves_recovery_link`: record;
   `set_status(fid, "recovered", "2026.02.15_10.30_fixture.eml")`; re-record.
   Assert status `"recovered"` and
   `recovered_date_file_name == "2026.02.15_10.30_fixture.eml"`.
3. `test_re_record_preserves_created_and_received_at`: record with
   `_failure(received_at="2026-02-15T10:30:00-08:00")`, then re-record with
   `_failure(received_at="2026-03-01T09:00:00-08:00")`. Assert
   `created_at` and `received_at` both still equal the first value, and
   `updated_at` is not None.
4. `test_first_record_honours_incoming_status`: a first-time
   `record_failure(_failure(status="recovered"))` stores `"recovered"`.
   This guards the recovery path in `parse_recovery.py`.

Before running, check that `_failure` passes `received_at` through. It uses
`base.update(overrides)`, so it does.

**Verify**: `uv run pytest tests/unit/test_parse_failure_store.py -q` → tests 1–3 **fail for `[dynamodb]` and pass for `[sqlite]`**. Test 4 passes on both. If SQLite fails any of them, see the STOP conditions.

### Step 2: Replace `put_item` with an `update_item` upsert

In `ParseFailureStore.record_failure` (`src/finance/parse_failure_store.py`),
keep all the value computation. Replace the `item` dict and `put_item` with
one `update_item` on `Key={"PK": self.USER_PK, "SK": f"FAIL#{sk_token}#{failure_id}"}`
that:

- **always sets** `FailureStage` and `UpdatedAt`, mirroring SQLite's `DO UPDATE SET`;
- sets every other attribute **only if absent**, using `if_not_exists`:
  `FailureId`, `ReceivedAt`, `FromEmail`, `Subject`, `FileName`,
  `DetectedInstitution`, `Status`, `RecoveredDateFileName`,
  `AlertClassifierResult`, `EmailJson`, `CreatedAt`.

Use an `ExpressionAttributeNames` alias for **every** attribute, for example
`#FailureStage`. Several of these names (`Status`, possibly others) are
reserved words, and aliasing all of them avoids guessing which. Build the
expression from a small ordered mapping so it stays readable:

```python
        always = {"FailureStage": failure.get("failure_stage", "no_parser_match"), "UpdatedAt": now}
        if_absent = {
            "FailureId": failure_id,
            "ReceivedAt": received_at,
            "FromEmail": failure.get("from_email") or email_details.get("from_email"),
            "Subject": failure.get("subject") or email_details.get("subject"),
            "FileName": failure.get("file_name") or email_details.get("file_name"),
            "DetectedInstitution": failure.get("detected_institution"),
            "Status": failure.get("status", "quarantined"),
            "RecoveredDateFileName": failure.get("recovered_date_file_name"),
            "AlertClassifierResult": self.coerce_classifier(classifier),
            "EmailJson": email_json,
            "CreatedAt": received_at,
        }
        names = {f"#{k}": k for k in (*always, *if_absent)}
        values = {f":{k}": v for k, v in (*always.items(), *if_absent.items())}
        clauses = [f"#{k} = :{k}" for k in always] + [f"#{k} = if_not_exists(#{k}, :{k})" for k in if_absent]
        self.table.update_item(
            Key={"PK": self.USER_PK, "SK": f"FAIL#{sk_token}#{failure_id}"},
            UpdateExpression="SET " + ", ".join(clauses),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
```

Keep the existing pruning comment. Add a comment that says: "Upsert
semantics mirror ParseFailureStoreLocal.record_failure's ON CONFLICT clause:
only the stage and UpdatedAt change on a re-record; review status and the
recovery link survive redelivery."

Update the abstract `record_failure` docstring in
`parse_failure_store_base.py` to state that contract, so both
implementations are bound by it.

**Verify**: `uv run pytest tests/unit/test_parse_failure_store.py -q` → all pass on both backends, including `TestParseFailureStoreLegacyDuplicates`.

### Step 3: Full gate and changelog

- `CHANGELOG.md` → `## [Unreleased]` → `### Fixed`: "On the AWS deployment, a dismissed or recovered email in Needs review no longer reappears when the same email is delivered again."
- **Verify**: `uv run pytest tests/ -m "not integration" -q -n 8` → 0 failures. `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pyright src/ && uv run python scripts/checks/check_changelog.py` → exit 0.

## Test plan

- 4 new contract tests run on both backends, so 8 test cases in total. Steps 1–2 show them red on DynamoDB, then green.
- Regression: the existing contract and legacy-duplicate tests, plus the parse-failure API and recovery suites.

## Done criteria

- [ ] `grep -n "put_item" src/finance/parse_failure_store.py` → no match inside `record_failure`. `create_table` or other methods may still use it.
- [ ] `grep -n "if_not_exists" src/finance/parse_failure_store.py` → at least 1 match
- [ ] `uv run pytest tests/unit/test_parse_failure_store.py -q` → all pass, with 8 new parametrized cases
- [ ] `uv run pytest tests/ -m "not integration" -q -n 8` → 0 failures
- [ ] Lint, format and pyright → exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` row 005 set to DONE

## STOP conditions

- A new test fails on **SQLite**. The reference behaviour differs from this
  plan's description, so the rule must be decided by a human.
- moto rejects the `update_item` expression, for example with an attribute
  name or value count limit. Report the exact error. Do not fall back to
  `put_item` with a read-before-write.
- Any caller relies on re-record *resetting* the status. Search
  `grep -rn "record_failure" src/` and read each call site. If one expects a
  re-record to flip a dismissed row back to quarantined, stop and report.

## Maintenance notes

- When a column is added to the parse-failure schema, decide whether it is
  "always update" or "keep first value" on **both** backends. The SQLite
  `DO UPDATE SET` list and the DynamoDB `always` mapping must stay the same set.
- Reviewers: confirm the SK computation is unchanged. Changing it would
  create new items instead of upserting.
- Out of scope, noted for later: SQLite re-uploads of a dismissed email
  return "quarantined" to the uploader while the row stays dismissed and
  hidden. The storage is correct, but the upload message may confuse. That's
  a UX question for the maintainer.
