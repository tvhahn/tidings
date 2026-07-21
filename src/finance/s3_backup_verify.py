"""Stateless verification of a user-owned S3 backup target.

Runs a sequence of checks against a bucket the user wants to mirror receipt
attachments and statement PDFs into: credentials present, bucket reachable, a
write probe round-trips, plus advisory public-access / versioning warnings.

Persists nothing — no config write, no state file. The frontend saves the
verified target via ``PUT /config`` afterwards. The sync engine and scheduler
live in a sibling module and never call this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.finance.app_config import _has_aws_credentials
from src.finance.aws_region import get_aws_region
from src.finance.s3_backup_shared import normalize_prefix

_MAX_ERROR_LEN = 300
_WRITE_PROBE_SUFFIX = ".tidings-write-probe"


@dataclass
class S3VerifyResult:
    ok: bool
    error: str | None
    warnings: list[str]


def _truncate(message: str) -> str:
    """Trim a provider error to a bounded length (mirrors _validate_openai_key)."""
    return message[:_MAX_ERROR_LEN]


def verify_backup_target(
    bucket: str,
    prefix: str | None = None,
    *,
    s3_client: Any | None = None,
) -> S3VerifyResult:
    """Check that ``bucket`` is a usable backup target.

    Checks run in order; the first hard failure returns ``ok=False``. Advisory
    warnings never flip ``ok``. Blocking (network I/O) — call via ``run_sync``
    from an async handler.
    """
    from botocore.exceptions import ClientError

    if not _has_aws_credentials():
        return S3VerifyResult(
            ok=False,
            error=("No AWS credentials found. Configure credentials with aws configure or environment variables."),
            warnings=[],
        )

    import boto3

    client = s3_client or boto3.client("s3", region_name=get_aws_region())

    # a. Bucket reachable.
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as e:
        return S3VerifyResult(ok=False, error=_map_head_bucket_error(e, bucket), warnings=[])
    except Exception as e:
        return S3VerifyResult(ok=False, error=_truncate(str(e)), warnings=[])

    # b. Write probe: put + delete a tiny object under the target prefix.
    probe_key = normalize_prefix(prefix) + _WRITE_PROBE_SUFFIX
    try:
        client.put_object(Bucket=bucket, Key=probe_key, Body=b"tidings")
        client.delete_object(Bucket=bucket, Key=probe_key)
    except ClientError as e:
        return S3VerifyResult(ok=False, error=_truncate(_client_error_message(e)), warnings=[])
    except Exception as e:
        return S3VerifyResult(ok=False, error=_truncate(str(e)), warnings=[])

    # c. Advisory warnings — never flip ok.
    warnings: list[str] = []
    warnings.extend(_public_access_warnings(client, bucket, ClientError))
    warnings.extend(_versioning_warnings(client, bucket, ClientError))

    return S3VerifyResult(ok=True, error=None, warnings=warnings)


def _client_error_message(e: Any) -> str:
    """Best-effort human message from a botocore ClientError."""
    err = getattr(e, "response", {}).get("Error", {}) if hasattr(e, "response") else {}
    return err.get("Message") or str(e)


def _map_head_bucket_error(e: Any, bucket: str) -> str:
    """Map a head_bucket ClientError to a calm, user-facing message."""
    response = getattr(e, "response", {}) or {}
    error = response.get("Error", {}) or {}
    # botocore surfaces the code as a string — numeric ("404") or named
    # ("NoSuchBucket", "AccessDenied").
    code = str(error.get("Code", ""))

    if code in {"404", "NoSuchBucket"}:
        return f"Bucket not found: {bucket}."
    if code in {"403", "AccessDenied", "Forbidden"}:
        return f"Access denied for bucket {bucket}. Check your IAM permissions."
    if code in {"301", "PermanentRedirect", "IllegalLocationConstraint"}:
        configured = get_aws_region()
        actual = _bucket_region_from_response(response)
        if actual:
            return (
                f"Bucket {bucket} is in region {actual}, but this app is configured "
                f"for {configured}. Set the app's region to match the bucket."
            )
        return (
            f"Bucket {bucket} is in a different region than the configured {configured}. "
            "Set the app's region to match the bucket."
        )
    return _truncate(_client_error_message(e))


def _bucket_region_from_response(response: dict[str, Any]) -> str | None:
    """Pull the bucket's real region from the ``x-amz-bucket-region`` header."""
    headers = response.get("ResponseMetadata", {}).get("HTTPHeaders", {}) or {}
    return headers.get("x-amz-bucket-region")


def _public_access_warnings(client: Any, bucket: str, client_error: type[Exception]) -> list[str]:
    """Advisory check: bucket should block all public access."""
    try:
        result = client.get_public_access_block(Bucket=bucket)
    except client_error as e:  # type: ignore[misc]
        code = str((getattr(e, "response", {}) or {}).get("Error", {}).get("Code", ""))
        if code == "NoSuchPublicAccessBlockConfiguration":
            return ["Bucket does not block all public access. Enabling S3 Block Public Access is recommended."]
        if code in {"AccessDenied", "403", "Forbidden"}:
            return ["Could not check public access settings."]
        return ["Could not check public access settings."]
    except Exception:
        return ["Could not check public access settings."]

    config = result.get("PublicAccessBlockConfiguration", {}) or {}
    flags = (
        config.get("BlockPublicAcls"),
        config.get("IgnorePublicAcls"),
        config.get("BlockPublicPolicy"),
        config.get("RestrictPublicBuckets"),
    )
    if not all(bool(flag) for flag in flags):
        return ["Bucket does not block all public access. Enabling S3 Block Public Access is recommended."]
    return []


def _versioning_warnings(client: Any, bucket: str, client_error: type[Exception]) -> list[str]:
    """Advisory check: versioning protects backups from accidental deletion."""
    try:
        result = client.get_bucket_versioning(Bucket=bucket)
    except client_error as e:  # type: ignore[misc]
        code = str((getattr(e, "response", {}) or {}).get("Error", {}).get("Code", ""))
        if code in {"AccessDenied", "403", "Forbidden"}:
            return ["Could not check bucket versioning."]
        return ["Could not check bucket versioning."]
    except Exception:
        return ["Could not check bucket versioning."]

    if result.get("Status") != "Enabled":
        return ["Bucket versioning is off. Enabling it protects backed-up files against accidental deletion."]
    return []
