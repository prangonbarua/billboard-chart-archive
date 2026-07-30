"""Wiring tests. These import app, which loads every CSV — slow by design.
Keep the fast unit tests in test_versus.py, which must never import app."""
import pandas as pd
import pytest


@pytest.fixture(scope='session')
def application():
    import app
    return app


def test_chart_dt_covers_every_loaded_chart(application):
    for key, (df, _dates) in application.CHART_DATA.items():
        if df is None or not len(df):
            continue
        dt = application.CHART_DT[key]
        assert len(dt) == len(df), f'{key}: dt length {len(dt)} != df length {len(df)}'
        assert dt.index.equals(df.index), f'{key}: dt index misaligned'
        assert pd.api.types.is_datetime64_any_dtype(dt), f'{key}: dt is not datetime64'
        assert dt.notna().all(), f'{key}: {dt.isna().sum()} unparseable dates'
