"""
pytest 共享 fixture
"""
from __future__ import annotations

import datetime
from contextlib import contextmanager
from unittest.mock import patch

import pytest


@pytest.fixture
def freeze_datetime():
    """冻结 datetime.datetime.now() + datetime.date.today() 到指定时间。

    用法：
        def test_something(freeze_datetime):
            with freeze_datetime(2026, 6, 28, 12, 0, 0):
                ...
    """
    @contextmanager
    def _freeze(y, m, d, h=0, mi=0, s=0):
        dt = datetime.datetime(y, m, d, h, mi, s)
        dt_date = dt.date()
        with (
            patch("datetime.datetime", **{"now.return_value": dt, "today.return_value": dt}),
        ):
            yield

    return _freeze
