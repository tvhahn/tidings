"""Tests for the stateless S3 backup-target verifier.

Uses ``moto``'s ``mock_aws`` so the checks exercise real botocore code paths.
The mock must wrap client *creation*, so the client is built inside the
context and passed via ``s3_client=`` — constructing it outside the context
would hit real AWS.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dummy AWS credentials so botocore is satisfied under moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")


def _make_bucket(
    *,
    block_public_access: bool = True,
    versioning: bool = True,
) -> Any:
    """Create an S3 client + a provisioned bucket inside an active moto context."""
    import boto3

    client = boto3.client("s3", region_name="us-west-2")
    client.create_bucket(Bucket="my-backup", CreateBucketConfiguration={"LocationConstraint": "us-west-2"})
    if block_public_access:
        client.put_public_access_block(
            Bucket="my-backup",
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
    if versioning:
        client.put_bucket_versioning(Bucket="my-backup", VersioningConfiguration={"Status": "Enabled"})
    return client


class TestVerifyBackupTarget:
    def test_happy_path_ok_no_warnings_and_probe_cleaned_up(self, aws_env: None) -> None:
        from moto import mock_aws

        from src.finance.s3_backup_verify import verify_backup_target

        with mock_aws():
            client = _make_bucket()
            result = verify_backup_target("my-backup", "receipts", s3_client=client)

            assert result.ok is True
            assert result.error is None
            assert result.warnings == []
            # The write probe must clean itself up — bucket has zero objects.
            listing = client.list_objects_v2(Bucket="my-backup")
            assert listing.get("KeyCount", 0) == 0
            assert "Contents" not in listing

    def test_nonexistent_bucket_returns_not_found(self, aws_env: None) -> None:
        from moto import mock_aws

        from src.finance.s3_backup_verify import verify_backup_target

        with mock_aws():
            import boto3

            client = boto3.client("s3", region_name="us-west-2")
            result = verify_backup_target("does-not-exist", s3_client=client)

            assert result.ok is False
            assert result.error is not None
            assert "not found" in result.error.lower()
            assert result.warnings == []

    def test_missing_public_access_block_warns_but_ok(self, aws_env: None) -> None:
        from moto import mock_aws

        from src.finance.s3_backup_verify import verify_backup_target

        with mock_aws():
            client = _make_bucket(block_public_access=False)
            result = verify_backup_target("my-backup", s3_client=client)

            assert result.ok is True
            assert any("public access" in w.lower() for w in result.warnings)

    def test_versioning_off_warns_but_ok(self, aws_env: None) -> None:
        from moto import mock_aws

        from src.finance.s3_backup_verify import verify_backup_target

        with mock_aws():
            client = _make_bucket(versioning=False)
            result = verify_backup_target("my-backup", s3_client=client)

            assert result.ok is True
            assert any("versioning" in w.lower() for w in result.warnings)

    def test_no_credentials_returns_early_without_s3_call(self, aws_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.finance.s3_backup_verify as verify_mod
        from src.finance.s3_backup_verify import verify_backup_target

        monkeypatch.setattr(verify_mod, "_has_aws_credentials", lambda: False)

        class _ExplodingClient:
            def __getattr__(self, name: str) -> Any:
                raise AssertionError(f"no S3 call expected, got {name}")

        result = verify_backup_target("my-backup", s3_client=_ExplodingClient())

        assert result.ok is False
        assert result.error is not None
        assert "no aws credentials" in result.error.lower()
        assert result.warnings == []
