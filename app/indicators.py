"""Pure, testable indicator engine.

No web/DB dependencies. Functions take pandas objects in and return pandas
objects out so they can be unit-tested in isolation and reused anywhere.

Indicator backend: this module prefers `pandas_ta` (verified working with
pandas_ta==0.4.71b0 + numpy 2.2.x + pandas 3.x in this project). If pandas_ta
is unavailable or errors at runtime, it transparently falls back to a native
NumPy/pandas implementation that produces IDENTICAL column names and
Wilder-smoothed semantics. The rest of the app does not care which path runs;
`INDICATOR_BACKEND` records the chosen path for diagnostics/UI.

Output column names are stable regardless of backend:
    rsi, macd, macd_signal, macd_hist
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Default indicator parameters (overridable from Settings at call sites).
RSI_LENGTH = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
SMA_DISTANCE_LENGTH = 20

# Detect pandas_ta availability once.
try:  # pragma: no cover - exercised indirectly
    import pandas_ta as _pta  # noqa: F401

    _HAVE_PTA = True
except Exception:  # pragma: no cover
    _HAVE_PTA = False

INDICATOR_BACKEND = "pandas_ta" if _HAVE_PTA else "native"


# ---------------------------------------------------------------------------
# Native fallback implementations (Wilder RSI, EMA MACD)
# ---------------------------------------------------------------------------
def _native_rsi(close: pd.Series, length: int = RSI_LENGTH) -> pd.Series:
    close = pd.Series(close, dtype="float64").reset_index(drop=True)
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    # Wilder's smoothing == EWM with alpha = 1/length, adjust=False.
    roll_up = up.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    roll_down = down.ewm(alpha=1.0 / length, min_periods=length, adjust=False).mean()
    rs = roll_up / roll_down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # Where average loss is zero -> RSI 100; where both zero -> NaN handled by ewm.
    rsi = rsi.where(roll_down != 0, 100.0)
    rsi[roll_up.isna()] = np.nan
    return rsi


def _native_macd(
    close: pd.Series,
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> pd.DataFrame:
    close = pd.Series(close, dtype="float64").reset_index(drop=True)
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False, min_periods=signal).mean()
    macd_hist = macd - macd_signal
    return pd.DataFrame(
        {"macd": macd, "macd_signal": macd_signal, "macd_hist": macd_hist}
    )


# ---------------------------------------------------------------------------
# Public single-series API (backend-agnostic)
# ---------------------------------------------------------------------------
def rsi(close: pd.Series, length: int = RSI_LENGTH) -> pd.Series:
    """Return RSI as a Series aligned to ``close``'s index."""
    s = pd.Series(close, dtype="float64")
    idx = s.index
    if _HAVE_PTA:
        try:
            out = _pta.rsi(s.reset_index(drop=True), length=length)
            if out is not None:
                out.index = idx
                return out.rename("rsi")
        except Exception:
            pass
    out = _native_rsi(s, length)
    out.index = idx
    return out.rename("rsi")


def macd(
    close: pd.Series,
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> pd.DataFrame:
    """Return DataFrame with columns macd, macd_signal, macd_hist."""
    s = pd.Series(close, dtype="float64")
    idx = s.index
    if _HAVE_PTA:
        try:
            res = _pta.macd(s.reset_index(drop=True), fast=fast, slow=slow, signal=signal)
            if res is not None and res.shape[1] >= 3:
                res = res.copy()
                res.columns = ["macd", "macd_hist", "macd_signal"][: res.shape[1]]
                # pandas_ta order is MACD, MACDh, MACDs -> normalise explicitly.
                cols = list(res.columns)
                # rebuild safely by name pattern
                out = pd.DataFrame(index=range(len(s)))
                out["macd"] = res.iloc[:, 0].values
                out["macd_hist"] = res.iloc[:, 1].values
                out["macd_signal"] = res.iloc[:, 2].values
                out = out[["macd", "macd_signal", "macd_hist"]]
                out.index = idx
                return out
        except Exception:
            pass
    out = _native_macd(s, fast, slow, signal)
    out.index = idx
    return out


def sma(close: pd.Series, length: int = SMA_DISTANCE_LENGTH) -> pd.Series:
    s = pd.Series(close, dtype="float64")
    return s.rolling(window=length, min_periods=length).mean().rename(f"sma{length}")


# ---------------------------------------------------------------------------
# Signal tagging
# ---------------------------------------------------------------------------
def rsi_signal(value: float, oversold: float = 35.0, overbought: float = 65.0) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Unknown"
    if value < oversold:
        return "Oversold"
    if value > overbought:
        return "Overbought"
    return "Neutral"


def macd_state(macd_val: float, signal_val: float) -> str:
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in (macd_val, signal_val)):
        return "Unknown"
    return "Bullish" if macd_val > signal_val else "Bearish"


def combined_signal(
    rsi_val: float,
    macd_val: float,
    signal_val: float,
    oversold: float = 35.0,
    overbought: float = 65.0,
) -> str:
    r = rsi_signal(rsi_val, oversold, overbought)
    m = macd_state(macd_val, signal_val)
    if r == "Oversold" and m == "Bullish":
        return "Strong Buy"
    if r == "Overbought" and m == "Bearish":
        return "Strong Sell"
    return "Neutral"


# ---------------------------------------------------------------------------
# Per-ticker computation over a multi-ticker tidy frame
# ---------------------------------------------------------------------------
def compute_indicators_for_series(
    df: pd.DataFrame,
    rsi_length: int = RSI_LENGTH,
    macd_fast: int = MACD_FAST,
    macd_slow: int = MACD_SLOW,
    macd_signal: int = MACD_SIGNAL,
    sma_length: int = SMA_DISTANCE_LENGTH,
) -> pd.DataFrame:
    """Compute indicators for a SINGLE ticker time-series.

    Input ``df`` must contain a 'close' column and be sorted by date ascending.
    Returns a copy with columns: rsi, macd, macd_signal, macd_hist, sma{N},
    dist_from_sma (fractional), and on the LAST row the values are the latest.
    """
    out = df.copy()
    if "close" not in out.columns:
        raise ValueError("compute_indicators_for_series requires a 'close' column")
    close = out["close"].astype("float64")
    out["rsi"] = rsi(close, rsi_length).values
    m = macd(close, macd_fast, macd_slow, macd_signal)
    out["macd"] = m["macd"].values
    out["macd_signal"] = m["macd_signal"].values
    out["macd_hist"] = m["macd_hist"].values
    sma_series = sma(close, sma_length)
    out[f"sma{sma_length}"] = sma_series.values
    with np.errstate(invalid="ignore", divide="ignore"):
        out["dist_from_sma"] = (close.values - sma_series.values) / sma_series.values
    return out
