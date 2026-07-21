"""Demo world-clock override — ``DEMO_TODAY`` pins the app's notion of "today".

The static demo's fixtures are generated against a backend whose data is
anchored to a fixed month (see ``demo_loader.DEMO_FREEZE_MONTH``). Services
that consume the real clock (budget elapsed fractions, historical-average
windows, forecasts) would otherwise bake the generator machine's date into
the fixtures. Setting ``DEMO_TODAY=YYYY-MM-DD`` during fixture generation
pins those computations to the demo world's "today" instead.

Real deployments never set the variable, so :func:`app_today` is exactly
"today in the configured app timezone" outside fixture generation.
"""

import logging
import os
from datetime import date, datetime

from src.finance.app_timezone import get_app_timezone

logger = logging.getLogger(__name__)

_ENV_DEMO_TODAY = "DEMO_TODAY"


def demo_today_override() -> date | None:
    """Parse ``DEMO_TODAY`` (``YYYY-MM-DD``) into a date.

    Returns None when unset or malformed (malformed values log a warning).
    """
    raw = os.environ.get(_ENV_DEMO_TODAY)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        logger.warning("Ignoring malformed %s=%r (expected YYYY-MM-DD)", _ENV_DEMO_TODAY, raw)
        return None


def app_today() -> date:
    """Today in the configured app timezone, honoring ``DEMO_TODAY`` when set."""
    return demo_today_override() or datetime.now(get_app_timezone()).date()
