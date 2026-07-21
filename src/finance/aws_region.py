"""Single source of truth for the AWS region used by DynamoDB/S3 clients.

`AWS_REGION` (or the SDK-standard `AWS_DEFAULT_REGION`) wins; the fallback
stays `us-west-2` for backwards compatibility with existing deployments
that predate the env var.
"""

from __future__ import annotations

import os

_FALLBACK_REGION = "us-west-2"


def get_aws_region() -> str:
    """Region for boto3 clients/resources created by this app."""
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or _FALLBACK_REGION
