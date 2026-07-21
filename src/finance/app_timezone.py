"""Timezone helpers driven by the `timezone` key in `data/config.json`.

Default is `America/Los_Angeles` for backwards compatibility with pre-OSS
deployments. Invalid zone names fall back to Pacific with a logged warning.
"""

import logging
import re
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.tz import gettz

from src.finance.app_config import get_config

logger = logging.getLogger(__name__)

_DEFAULT_TZ_NAME = "America/Los_Angeles"

# Recognizes ANY trailing timezone token stamped by the ingest path's
# `%m/%d/%Y %H:%M %Z` format: an all-caps abbreviation (PST, MST, NST, CET…)
# or a numeric UTC offset (+04, -0330, +05:45). Used by the backup import guard
# to detect an already-stamped date so it is never reattached (double-stamped),
# regardless of zone. NOTE the deliberate asymmetry with TZ_ABBREV_SUFFIX_RE
# below: import must *recognize* every token, but export strips only the
# alphabetic ones.
TZ_SUFFIX_RE = re.compile(r"\s+(?:[A-Z]{2,5}|[+-]\d{2}(?::?\d{2})?)$")

# Matches ONLY the alphabetic-abbreviation form of the trailing token. Used by
# the backup CSV export strip site. The asymmetry with TZ_SUFFIX_RE is
# deliberate: `_reattach_configured_tz` on import can reproduce an alphabetic
# abbreviation exactly (via strftime "%Z"), so stripping it keeps the round
# trip lossless. But a numeric "%Z" token like "+04" reattaches via "%z" as
# "+0400" — a different string that would change the dedup hash — so numeric
# offsets must SURVIVE export unstripped. This also matches pre-fix behavior:
# the old four-zone regex (PST|PDT|EST|EDT) never stripped numeric tokens
# either.
TZ_ABBREV_SUFFIX_RE = re.compile(r"\s+[A-Z]{2,5}$")

# PST/PDT aliases historically appear in stored `date` strings and in many test
# fixtures. They literally mean Pacific, so resolve them to Pacific regardless
# of the user's configured timezone — otherwise legacy rows re-parsed after a
# zone switch would shift.
_LEGACY_TZINFOS: dict[str, tzinfo | None] = {
    "PDT": gettz(_DEFAULT_TZ_NAME),
    "PST": gettz(_DEFAULT_TZ_NAME),
}


def get_app_timezone() -> ZoneInfo:
    """Return the user-configured IANA timezone, falling back to Pacific."""
    tz_name = get_config().get("timezone") or _DEFAULT_TZ_NAME
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Invalid timezone %r in config; falling back to %s", tz_name, _DEFAULT_TZ_NAME)
        return ZoneInfo(_DEFAULT_TZ_NAME)


def now_local() -> datetime:
    """Current instant as a tz-aware datetime in the configured app timezone.

    The tzinfo comes from :func:`get_app_timezone`, so the wall-clock reading
    honors the user's `timezone` config rather than the container's UTC clock.
    Callers that need a bare local `date` should use
    :func:`src.finance.demo_clock.app_today` instead — it also honors the demo
    world-clock override.
    """
    return datetime.now(get_app_timezone())


def get_tzinfos() -> dict[str, tzinfo | None]:
    """tzinfos map for `dateutil.parse`.

    - PST/PDT always resolve to Pacific (legacy-data invariant).
    - The configured zone's winter + summer abbreviations are added too so
      re-parsing stored `date` strings (e.g. `" CEST"` for a Berlin user)
      does not emit `UnknownTimezoneWarning` or return naive datetimes.
    """
    tzinfos: dict[str, tzinfo | None] = dict(_LEGACY_TZINFOS)
    tz = get_app_timezone()
    dateutil_tz = gettz(str(tz))
    if dateutil_tz is not None:
        # Sample January (standard time) and July (likely DST) to capture both
        # abbreviations the configured zone emits via strftime("%Z").
        for probe in (datetime(2026, 1, 15, tzinfo=tz), datetime(2026, 7, 15, tzinfo=tz)):
            abbrev = probe.strftime("%Z")
            # Skip numeric offset tokens ("+01", "-0800") — dateutil parses
            # those natively and using them as tzinfos keys is nonsensical.
            if abbrev and not abbrev.startswith(("+", "-")):
                tzinfos.setdefault(abbrev, dateutil_tz)
    return tzinfos
