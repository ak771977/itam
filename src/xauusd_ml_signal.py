"""
ML signal engine for XAUUSD entries (shared with the flipped grid variant).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import joblib
import pandas as pd

from src.features.xauusd_features import (
    add_indicator_columns,
    extract_feature_row,
    required_bars_for_features,
)

# Mirrors the marti feature order used during training
FEATURE_COLUMNS = (
    "RMI",
    "ADX",
    "ATR_pips",
    "Velocity5",
    "Velocity15",
    "Return1",
    "Return5",
    "Body",
    "Range",
    "WickUpper",
    "WickLower",
    "HourSin",
    "HourCos",
    "price_vs_sma20",
    "price_vs_sma50",
    "sma20_slope5",
    "ema20_slope5",
    "near_sma20",
)


class XAUUSDMLSignalEngine:
    def __init__(
        self,
        model_path: Path,
        meta_path: Path,
        buy_threshold: float = 0.60,
        sell_threshold: float = 0.60,
        min_probability_gap: float = 0.05,
    ):
        self.model_path = Path(model_path)
        self.meta_path = Path(meta_path)
        self.model = joblib.load(self.model_path)

        classifier = self.model.named_steps["classifier"]
        classes = classifier.classes_
        self.class_to_index = {int(label): idx for idx, label in enumerate(classes)}

        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.feature_columns = FEATURE_COLUMNS
        self.min_probability_gap = min_probability_gap
        self._latest_features: Optional[pd.Series] = None

    def _bars_to_dataframe(self, rates) -> pd.DataFrame:
        df = pd.DataFrame(rates)
        df = df.rename(
            columns={
                "time": "Time",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "tick_volume": "TickVol",
            }
        )
        df["Time"] = pd.to_datetime(df["Time"], unit="s")
        df = df.sort_values("Time").reset_index(drop=True)
        return df

    def evaluate(self, rates) -> dict:
        """
        Update internal feature snapshot using the latest MT5 rates.
        Returns dict with keys: signal, buy_proba, sell_proba.
        """
        df = self._bars_to_dataframe(rates)
        if len(df) < required_bars_for_features():
            return {"signal": None, "buy_proba": 0.0, "sell_proba": 0.0}

        enriched = add_indicator_columns(df).dropna()
        features = extract_feature_row(enriched, self.feature_columns)
        if features is None:
            return {"signal": None, "buy_proba": 0.0, "sell_proba": 0.0}

        self._latest_features = features
        feature_df = pd.DataFrame([features.values], columns=self.feature_columns)
        proba = self.model.predict_proba(feature_df)[0]

        buy_proba = proba[self.class_to_index.get(1, 0)]
        sell_proba = proba[self.class_to_index.get(-1, 0)]

        signal = None
        if (
            buy_proba >= self.buy_threshold
            and buy_proba - sell_proba >= self.min_probability_gap
            and buy_proba > sell_proba
        ):
            signal = "BUY"
        elif (
            sell_proba >= self.sell_threshold
            and sell_proba - buy_proba >= self.min_probability_gap
            and sell_proba > buy_proba
        ):
            signal = "SELL"

        return {
            "signal": signal,
            "buy_proba": float(buy_proba),
            "sell_proba": float(sell_proba),
        }

    @property
    def latest_features(self) -> Optional[pd.Series]:
        return self._latest_features
