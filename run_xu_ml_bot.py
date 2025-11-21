"""
Flipped XAUUSD ML bot runner.
- Uses the marti ML entry model for gold
- Manages baskets with the flipped-grid exit/add logic
- Includes timed log rotation and archive sweep
"""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import sys
import time
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

from src.features.xauusd_features import required_bars_for_features
from src.flipped_strategy import FlippedStrategy
from src.log_archiver import LogArchiver
from src.mt5_client import MT5Client
from src.risk_manager import RiskManager
from src.xauusd_ml_signal import XAUUSDMLSignalEngine

logger = logging.getLogger("itam.xu_ml")
logger.addHandler(logging.NullHandler())


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def resolve_mt5_password(mt5_cfg: dict) -> str:
    password = mt5_cfg.get("password")
    if password:
        return password
    password_env = mt5_cfg.get("password_env")
    if password_env:
        env_val = os.environ.get(password_env)
        if env_val:
            logger.info("MT5 password loaded from env %s", password_env)
            return env_val
    raise ValueError("MT5 password must be set in config or via password_env.")


def configure_logging(log_cfg: dict):
    log_file = log_cfg.get("file", "logs/xu_ml_bot.log")
    log_level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    console_enabled = log_cfg.get("console", True)

    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=7, encoding="utf-8")
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)

    if console_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)
        root_logger.addHandler(console_handler)


def atr_pips_from_rates(rates: list, period: int = 14) -> Optional[float]:
    if len(rates) < period + 1:
        return None
    df = pd.DataFrame(rates)
    tr_components = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    )
    atr = tr_components.max(axis=1).rolling(window=period, min_periods=period).mean().iloc[-1]
    if pd.isna(atr):
        return None
    # Gold pip multiplier is 100 (0.01 units)
    return float(atr * 100)


class FlippedXUMLBot:
    def __init__(self, config_path: str):
        self.config = load_config(config_path)
        log_cfg = self.config.get("logging", {})
        configure_logging(log_cfg)

        self.symbol = self.config.get("symbol", "XAUUSD")
        self.timeframe = getattr(mt5, f"TIMEFRAME_{self.config.get('timeframe', 'M1')}", mt5.TIMEFRAME_M1)
        self.poll_seconds = float(self.config.get("poll_seconds", 1.0))
        self.ml_cfg = self.config.get("ml", {})
        self.mt5_cfg = self.config.get("mt5", {})
        self.trading_cfg = self.config.get("trading", {})
        self.log_archiver = LogArchiver(
            logs_dir=os.path.dirname(log_cfg.get("file", "logs/xu_ml_bot.log")) or "logs",
            months_to_keep=log_cfg.get("archive_months", 3),
            log_filename=os.path.basename(log_cfg.get("file", "xu_ml_bot.log")),
        )

        password = resolve_mt5_password(self.mt5_cfg)
        MT5Client.connect(
            login=self.mt5_cfg.get("account"),
            password=password,
            server=self.mt5_cfg.get("server"),
            path=self.mt5_cfg.get("terminal_path"),
        )

        slippage = int(self.mt5_cfg.get("slippage_points", 100))
        self.client = MT5Client(
            symbol=self.symbol,
            magic_number=self.mt5_cfg.get("magic_number", 900001),
            slippage_points=slippage,
            comment=self.mt5_cfg.get("comment_base", "XU_ML_FLIPPED"),
        )
        self.strategy = FlippedStrategy(symbol=self.symbol, config=self.config)
        self.risk_manager = RiskManager(self.config)
        self.ml_engine = XAUUSDMLSignalEngine(
            model_path=Path(self.ml_cfg.get("model_path", "models/xauusd_entry_model.pkl")),
            meta_path=Path(self.ml_cfg.get("meta_path", "models/xauusd_entry_model_meta.json")),
            buy_threshold=self.ml_cfg.get("buy_threshold", 0.62),
            sell_threshold=self.ml_cfg.get("sell_threshold", 0.60),
            min_probability_gap=self.ml_cfg.get("min_probability_gap", 0.05),
        )
        self._sync_existing_basket()
        logger.info("Flipped XU ML bot ready for %s timeframe=%s", self.symbol, self.config.get("timeframe", "M1"))

    def _sync_existing_basket(self):
        positions = self.client.positions()
        if not positions:
            return
        direction = "BUY" if positions[0].type == mt5.POSITION_TYPE_BUY else "SELL"
        self.strategy.basket_open = True
        self.strategy.basket_direction = direction
        self.strategy.basket_positions = [
            {"price": pos.price_open, "volume": pos.volume, "ticket": pos.ticket} for pos in positions
        ]
        # Roughly re-arm BE if we already have at least 2 legs
        self.strategy._be_armed = len(positions) >= 2  # pylint: disable=protected-access
        self.strategy.mark_synced_from_mt5()
        logger.info("Synced existing MT5 basket: %d legs %s", len(positions), direction)

    def _account_info(self):
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"Unable to fetch account info: {mt5.last_error()}")
        return info._asdict()

    def _price_for_direction(self, direction: str) -> float:
        tick = self.client.latest_tick()
        if direction == "BUY":
            return tick.ask
        if direction == "SELL":
            return tick.bid
        return (tick.ask + tick.bid) / 2

    def _maybe_close(self, current_price: float, atr_pips: Optional[float]):
        should_close, reason = self.strategy.should_close_basket(current_price, atr_pips=atr_pips)
        if not should_close:
            return
        closed = self.client.close_all()
        self.strategy.close_basket(current_price, reason if closed else f"{reason}_FAILED")

    def _maybe_add(self, current_price: float):
        if not self.strategy.should_add_to_basket(current_price):
            return
        next_vol = self.strategy._compute_next_volume()  # pylint: disable=protected-access
        order = self.client.open_market(self.strategy.basket_direction, next_vol)
        self.strategy.add_to_basket(price=order.price, ticket=order.ticket)

    def _maybe_open_new(self, rates):
        ml_result = self.ml_engine.evaluate(rates)
        signal = ml_result.get("signal")
        if not signal:
            return
        account_info = self._account_info()
        self.risk_manager.update_daily(account_info.get("profit", 0.0))
        ok, reason = self.risk_manager.can_open_position(account_info)
        if not ok:
            logger.warning("Skipping signal due to risk gate: %s", reason)
            return

        volume = self.strategy.initial_volume
        order = self.client.open_market(signal, volume)
        self.strategy.open_basket(signal, order.price, ticket=order.ticket)
        logger.info("[ML ENTRY] %s p=%.2f/%.2f", signal, ml_result.get("buy_proba"), ml_result.get("sell_proba"))

    def run(self):
        logger.info("Starting main loop poll=%ss", self.poll_seconds)
        try:
            while True:
                rates = self.client.copy_rates(self.timeframe, count=max(120, required_bars_for_features()))
                atr_val = atr_pips_from_rates(rates)
                tick_price = self._price_for_direction(self.strategy.basket_direction or "MID")

                if self.strategy.basket_open:
                    self._maybe_close(tick_price, atr_val)
                    if self.strategy.basket_open:
                        self._maybe_add(tick_price)
                else:
                    self._maybe_open_new(rates)

                # Avoid log spam and keep archives rotating
                if time.localtime().tm_hour == 0 and time.localtime().tm_min < 5:
                    self.log_archiver.archive_old_logs()
                time.sleep(self.poll_seconds)
        except KeyboardInterrupt:
            logger.info("Shutdown requested, closing baskets if any...")
            if self.strategy.basket_open:
                self.client.close_all()
        finally:
            mt5.shutdown()
            logger.info("MT5 shut down")


def main():
    parser = argparse.ArgumentParser(description="Run the flipped XAUUSD ML bot.")
    parser.add_argument("--config", default="config/config_xu_ml.json", help="Path to config JSON")
    args = parser.parse_args()
    bot = FlippedXUMLBot(config_path=args.config)
    bot.run()


if __name__ == "__main__":
    main()
