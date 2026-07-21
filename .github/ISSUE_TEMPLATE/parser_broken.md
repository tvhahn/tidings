---
name: Parser broken
about: A bank email is not being parsed correctly
title: '[PARSER] '
labels: 'bug,parser'
---

### Which institution?

<!-- Delete the ones that don't apply, or fill in "Other". -->

- RBC
- CIBC
- MBNA
- Simplii
- PC Financial
- Other: <!-- name the institution -->

### Subject line of the failing email

<!-- Paste the EXACT subject line of the email that failed to parse. -->

```
<subject here>
```

### Redacted email body

> **IMPORTANT — redaction rules:** Parsers match on structure and field
> ordering, so please **preserve the formatting and layout** of the original
> email. Only redact sensitive values as follows:
>
> - Replace dollar amounts with `$XX.XX`
> - Replace merchant / payee names with `[MERCHANT]`
> - Replace card last-4 digits with `[XXXX]`
> - Replace account numbers with `[ACCOUNT]`
>
> Do **not** remove whitespace, reorder fields, or collapse line breaks — that
> is exactly what the parser looks for.

```
<paste redacted email body here>
```

### Logs

<!-- One of the following, depending on how you're running the app: -->

**Self-hosted (Docker):**

```
docker logs imap-poller 2>&1 | tail -100
```

**AWS Lambda:** paste the relevant CloudWatch log group output for the failing
invocation.

```
<logs here>
```

### App version

<!-- Version from `pyproject.toml` (or git commit SHA if running from source). -->

### Anything else?

<!-- Recent changes, first time this email type has been seen, etc. -->
