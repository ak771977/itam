"""
Feature engineering utilities shared by the flipped XAUUSD ML entry pipeline.
Adapted from the marti stack to keep runtime dependencies light.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd


def load_m1_history(csv_path: Path) -> pd.DataFrame:
    """Load raw M1 history exported from MT5 (tab-separated or parquet)."""
    csv_path = Path(csv_path)
    if csv_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(csv_path)
    else:
        encodings = ("utf-8", "utf-16", "utf-16-le", "cp1252", "latin-1")
        last_exc = None
        for enc in encodings:
            try:
                df = pd.read_csv(csv_path, sep="\t", encoding=enc)
                break
            except UnicodeDecodeError as exc:
                last_exc = exc
                continue
        else:
            raise last_exc or UnicodeDecodeError("utf-8", b"", 0, 1, "Unable to decode history file")

    if "Time" not in df.columns:
        if {"Date", "Time"}.issubset(df.columns):
            df["DateTime"] = pd.to_datetime(df["Date"] + " " + df["Time"])
            df = df.drop(columns=["Date", "Time"]).rename(columns={"DateTime": "Time"})
        elif "DateTime" in df.columns:
            df = df.rename(columns={"DateTime": "Time"})
        else:
            raise ValueError("History file missing Time column")

    df["Time"] = pd.to_datetime(df["Time"])
    expected_cols = {"Open", "High", "Low", "Close"}
    if not expected_cols.issubset(set(df.columns)):
        raise ValueError("History file missing OHLC columns")

    return df.sort_values("Time").reset_index(drop=True)


def _calculate_rmi(close: pd.Series, period: int = 14, momentum_period: int = 5) -> pd.Series:
    momentum = close.diff(momentum_period)
    gain = momentum.where(momentum > 0, 0.0)
    loss = -momentum.where(momentum < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    tr_components = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    )
    tr = tr_components.max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()

    up_move = high.diff()
    down_move = low.shift().sub(low)
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    plus_di = 100 * plus_dm.rolling(window=period, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.rolling(window=period, min_periods=period).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(window=period, min_periods=period).mean()


def add_indicator_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Append indicator columns required by the ML pipeline."""
    df = df.copy()
    df["RMI"] = _calculate_rmi(df["Close"])
    df["ADX"] = _calculate_adx(df)

    tr_components = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift(1)).abs(),
            (df["Low"] - df["Close"].shift(1)).abs(),
        ],
        axis=1,
    )
    df["ATR_pips"] = tr_components.max(axis=1).rolling(window=14, min_periods=14).mean() * 100

    df["Velocity5"] = df["Close"].diff(5) * 100 / 5
    df["Velocity15"] = df["Close"].diff(15) * 100 / 15
    df["Return1"] = df["Close"].pct_change(1) * 100
    df["Return5"] = df["Close"].pct_change(5) * 100
    df["Body"] = df["Close"] - df["Open"]
    df["Range"] = df["High"] - df["Low"]
    df["WickUpper"] = df["High"] - df[["Open", "Close"]].max(axis=1)
    df["WickLower"] = df[["Open", "Close"]].min(axis=1) - df["Low"]
    df["Hour"] = df["Time"].dt.hour
    df["HourSin"] = np.sin(2 * np.pi * df["Hour"] / 24.0)
    df["HourCos"] = np.cos(2 * np.pi * df["Hour"] / 24.0)
    pip_multiplier = 100.0 if df["Close"].abs().mean() > 10 else 10000.0
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["price_vs_sma20"] = (df["Close"] - df["SMA20"]) * pip_multiplier
    df["price_vs_sma50"] = (df["Close"] - df["SMA50"]) * pip_multiplier
    df["sma20_slope5"] = (df["SMA20"] - df["SMA20"].shift(5)) * pip_multiplier
    df["ema20_slope5"] = (df["EMA20"] - df["EMA20"].shift(5)) * pip_multiplier
    df["near_sma20"] = (df["price_vs_sma20"].abs() <= (5 if pip_multiplier > 1000 else 50)).astype(int)
    df = df.drop(columns=["Hour", "SMA20", "SMA50", "EMA20"])
    return df


def prepare_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure indicators added and drop rows with missing values."""
    enriched = add_indicator_columns(df)
    return enriched.dropna().reset_index(drop=True)


def required_bars_for_features() -> int:
    """Minimum number of bars needed before all features stabilise."""
    return 60


def extract_feature_row(enriched_df: pd.DataFrame, feature_columns: Sequence[str]) -> Optional[pd.Series]:
    """Return the latest feature row if the dataframe contains enough history."""
    if len(enriched_df) == 0:
        return None
    latest = enriched_df.iloc[-1]
    latest_slice = latest.loc[list(feature_columns)]
    if latest_slice.isna().any():
        return None
    return latest_slice
