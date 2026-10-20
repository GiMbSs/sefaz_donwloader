from datetime import date

import pytest


def test_monthly_parts_include_leap_day_and_year_boundary():
    from apps.fiscal.atf.types import Period
    from apps.fiscal.services.periods import split_period

    assert split_period(Period(date(2024, 1, 31), date(2024, 3, 2))) == (
        Period(date(2024, 1, 31), date(2024, 1, 31)),
        Period(date(2024, 2, 1), date(2024, 2, 29)),
        Period(date(2024, 3, 1), date(2024, 3, 2)),
    )
    assert len(split_period(Period(date(2024, 12, 31), date(2025, 1, 2)))) == 2


def test_period_rejects_inverted_dates():
    from apps.fiscal.atf.types import Period

    with pytest.raises(ValueError):
        Period(date(2024, 2, 2), date(2024, 2, 1))


def test_active_key_normalizes_format_order():
    from apps.fiscal.atf.types import Period
    from apps.fiscal.services.periods import active_request_key

    period = Period(date(2024, 1, 1), date(2024, 1, 31))
    assert active_request_key(1, period, ("xml", "txt")) == active_request_key(
        1, period, ("txt", "xml")
    )
    assert active_request_key(1, period, ("xml",)) != active_request_key(
        2, period, ("xml",)
    )
