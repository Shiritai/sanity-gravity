"""The suite-wide Hypothesis profile keeps timing out of the verdict.

Under CPU starvation a property test failed with "Unreliable test
timings" (deadline) or "Input generation is slow" (too_slow) and passed
on rerun. Both checks are wall-clock, so they are off for every test.
"""
from __future__ import annotations

from hypothesis import HealthCheck, settings


def test_no_per_example_deadline():
    assert settings.default.deadline is None


def test_slow_generation_is_not_a_failure():
    assert HealthCheck.too_slow in settings.default.suppress_health_check
