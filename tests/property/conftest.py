"""Hypothesis profiles for the property-test suite.

Two profiles are registered:

- ``ci``  — 200 examples per property, no deadline, slow-health-check
  suppressed. Intended for CI where wall-clock is cheap but coverage matters.
- ``dev`` — 100 examples per property, 500ms deadline. Intended for local
  iteration where fast feedback matters.

The ``dev`` profile is loaded by default. CI can opt in via
``HYPOTHESIS_PROFILE=ci`` (hypothesis picks that env var up automatically).
"""

from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "dev",
    max_examples=100,
    deadline=500,
)
settings.load_profile("dev")
