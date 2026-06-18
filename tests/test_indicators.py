"""RSI & MACD vs known fixtures; signal tagging; backend equivalence."""
import numpy as np
import pandas as pd

from app import indicators as ind


# Classic Wilder/StockCharts RSI example (well-known reference series).
WILDER_CLOSE = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
    45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
    46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22,
]


def _reference_wilder_rsi_ewm(close, length=14):
    """Independent reference: Wilder RSI via RMA (alpha=1/length) EWM seeding.

    This is the standard 'recursive' Wilder smoothing used by pandas_ta and our
    native implementation. Hand-derived here so the test is a genuine fixture
    check rather than a tautology.
    """
    s = pd.Series(close, dtype="float64")
    delta = s.diff()
    gain = delta.clip(lower=0.0).tolist()
    loss = (-delta.clip(upper=0.0)).tolist()
    n = len(s)
    ag = [float("nan")] * n
    al = [float("nan")] * n
    a = 1.0 / length
    for i in range(1, n):
        g, lo = gain[i], loss[i]
        if i == 1:
            ag[i], al[i] = g, lo
        else:
            ag[i] = a * g + (1 - a) * ag[i - 1]
            al[i] = a * lo + (1 - a) * al[i - 1]
    out = []
    for i in range(n):
        if i < length or al[i] == 0:
            out.append(100.0 if (i >= length and al[i] == 0) else float("nan"))
        else:
            rs = ag[i] / al[i]
            out.append(100.0 - 100.0 / (1.0 + rs))
    return pd.Series(out)


def test_rsi_bounds_and_known_fixture():
    s = pd.Series(WILDER_CLOSE)
    r = ind.rsi(s, length=14)
    valid = r.dropna()
    # RSI must be within [0, 100]
    assert (valid >= 0).all() and (valid <= 100).all()
    # Match an independent Wilder-RMA reference at the fully-warmed tail.
    ref = _reference_wilder_rsi_ewm(WILDER_CLOSE, 14)
    mask = r.notna() & ref.notna()
    assert mask.sum() >= 10
    assert (r[mask].values - ref[mask].values).__abs__().max() < 1e-6


def test_rsi_monotonic_uptrend_high():
    # strictly increasing series -> RSI should approach 100
    s = pd.Series(np.arange(1, 60, dtype=float))
    r = ind.rsi(s, 14).dropna()
    assert r.iloc[-1] > 95


def test_rsi_monotonic_downtrend_low():
    s = pd.Series(np.arange(60, 1, -1, dtype=float))
    r = ind.rsi(s, 14).dropna()
    assert r.iloc[-1] < 5


def test_macd_columns_and_relationship():
    np.random.seed(7)
    close = pd.Series(100 + np.cumsum(np.random.randn(120)))
    m = ind.macd(close, 12, 26, 9)
    assert list(m.columns) == ["macd", "macd_signal", "macd_hist"]
    valid = m.dropna()
    # hist == macd - signal by construction
    assert np.allclose((valid["macd"] - valid["macd_signal"]).values, valid["macd_hist"].values, atol=1e-8)


def test_native_matches_pandas_ta_rsi_when_available():
    # If pandas_ta is the backend, the native fallback should match closely.
    np.random.seed(11)
    close = pd.Series(100 + np.cumsum(np.random.randn(200)))
    native = ind._native_rsi(close, 14)
    public = ind.rsi(close, 14)
    mask = native.notna() & public.notna()
    # Wilder RSI is deterministic; both paths must agree very tightly.
    assert (native[mask] - public[mask]).abs().max() < 1e-6


def test_signal_tags():
    assert ind.rsi_signal(25) == "Oversold"
    assert ind.rsi_signal(75) == "Overbought"
    assert ind.rsi_signal(50) == "Neutral"
    assert ind.macd_state(1.0, 0.5) == "Bullish"
    assert ind.macd_state(0.1, 0.5) == "Bearish"
    assert ind.combined_signal(25, 1.0, 0.5) == "Strong Buy"
    assert ind.combined_signal(75, 0.1, 0.5) == "Strong Sell"
    assert ind.combined_signal(50, 1.0, 0.5) == "Neutral"


def test_compute_indicators_for_series_columns():
    np.random.seed(3)
    df = pd.DataFrame({
        "date": pd.bdate_range("2024-01-01", periods=80),
        "close": 100 + np.cumsum(np.random.randn(80)),
    })
    out = ind.compute_indicators_for_series(df)
    for col in ["rsi", "macd", "macd_signal", "macd_hist", "dist_from_sma"]:
        assert col in out.columns
