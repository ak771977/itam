"""
Flipped grid strategy:
- Adds on favorable price movement (pyramiding into strength)
- Hard stop is tiny; stop moves to breakeven quickly
- Exits via trailing giveback instead of fixed TP
"""
from typing import Dict, List, Optional, Tuple
import logging


class FlippedStrategy:
    def __init__(self, symbol: str = "EURUSD", config: Optional[dict] = None):
        self.symbol = symbol
        self.logger = logging.getLogger(__name__)

        # Pip math
        sym_upper = symbol.upper()
        if "XAU" in sym_upper or "GOLD" in sym_upper:
            self.pip_multiplier = 100
            self.pip_value_per_lot = 1.0
        elif "JPY" in sym_upper:
            self.pip_multiplier = 100
            self.pip_value_per_lot = 10.0
        else:
            self.pip_multiplier = 10000
            self.pip_value_per_lot = 10.0

        strategy_cfg = config.get("strategy", {}) if config else {}

        # Core spacing/sizing
        self.add_distance_pips = float(strategy_cfg.get("add_distance_pips", 5.0))
        self.initial_volume = float(strategy_cfg.get("initial_volume", 0.02))
        self.volume_multiplier = float(strategy_cfg.get("volume_multiplier", 1.1))
        self.max_positions = int(strategy_cfg.get("max_positions", 6))
        self.max_total_volume = float(strategy_cfg.get("max_total_volume", 2.0))

        # Marti-style targets (profit per lot and TP multiple for mirrored SL)
        self.marti_profit_per_lot = float(
            strategy_cfg.get("marti_profit_per_lot", self._default_profit_per_lot(symbol))
        )
        self.marti_tp_multiple = float(strategy_cfg.get("marti_tp_multiple", 2.0))

        # Protection parameters
        self.hard_stop_dollars = float(strategy_cfg.get("hard_stop_dollars", 0.0))
        self.be_buffer_pips = float(strategy_cfg.get("be_buffer_pips", 1.0))
        self.trail_giveback_pct = float(strategy_cfg.get("trail_giveback_pct", 0.4))
        self.trail_atr_k = float(strategy_cfg.get("trail_atr_k", 0.0))
        self.trail_min_profit = float(strategy_cfg.get("trail_min_profit", 0.0))
        self.trail_start_multiple = float(strategy_cfg.get("trail_start_multiple", 0.5))
        self.trail_enabled = bool(strategy_cfg.get("trail_enabled", True))
        self.min_ticks_for_trail = int(strategy_cfg.get("min_ticks_for_trail", 0))
        self.arm_after_add = bool(strategy_cfg.get("arm_after_add", True))
        self.arm_profit_dollars = float(strategy_cfg.get("arm_profit_dollars", 0.0))
        self.be_arm_profit_multiple = float(strategy_cfg.get("be_arm_profit_multiple", 0.3))
        self.min_ticks_for_be = int(strategy_cfg.get("min_ticks_for_be", 0))
        self.resume_grace_ticks = int(strategy_cfg.get("resume_grace_ticks", 3))

        # State
        self.basket_open = False
        self.basket_direction: Optional[str] = None
        self.basket_positions: List[Dict] = []
        self.mfe_profit = 0.0  # max favorable excursion
        self.best_price: Optional[float] = None
        self._be_armed = False
        self._resume_grace_remaining = 0
        self._ticks_open = 0
        self._skip_marti_stop = False

        self.logger.info(
            "FlippedStrategy init | add=%.2f pips, vol0=%.2f, mult=%.2f, hard_stop=$%.2f, trail=%.0f%%",
            self.add_distance_pips,
            self.initial_volume,
            self.volume_multiplier,
            self.hard_stop_dollars,
            self.trail_giveback_pct * 100,
        )

    # --- Helpers -----------------------------------------------------
    @staticmethod
    def _default_profit_per_lot(symbol: str) -> float:
        sym_upper = symbol.upper()
        if "XAU" in sym_upper or "GOLD" in sym_upper:
            return 134.0
        if "JPY" in sym_upper:
            return 49.0
        if sym_upper == "EURUSD":
            return 49.0
        return 40.0

    def _weighted_entry(self) -> float:
        total_vol = sum(p["volume"] for p in self.basket_positions)
        if total_vol <= 0:
            return 0.0
        numer = sum(p["volume"] * p["price"] for p in self.basket_positions)
        return numer / total_vol

    def _current_profit(self, current_price: float) -> float:
        if not self.basket_open:
            return 0.0
        profit = 0.0
        direction_sign = 1 if self.basket_direction == "BUY" else -1
        for pos in self.basket_positions:
            pips = direction_sign * (current_price - pos["price"]) * self.pip_multiplier
            profit += pips * pos["volume"] * self.pip_value_per_lot
        return profit

    def _update_mfe(self, current_profit: float):
        if current_profit > self.mfe_profit:
            self.mfe_profit = current_profit

    def _arm_breakeven_if_ready(self, current_profit: float):
        if self._be_armed:
            return
        if self._ticks_open < self.min_ticks_for_be:
            return
        if self.arm_after_add and len(self.basket_positions) >= 2:
            self._be_armed = True
            return
        if self.arm_profit_dollars > 0 and current_profit >= self.arm_profit_dollars:
            self._be_armed = True
            return
        # Dynamic BE arm based on marti-sized stop
        total_vol = sum(p["volume"] for p in self.basket_positions)
        marti_stop = total_vol * self.marti_profit_per_lot
        if marti_stop > 0 and self.be_arm_profit_multiple > 0:
            if current_profit >= marti_stop * self.be_arm_profit_multiple:
                self._be_armed = True

    def _compute_next_volume(self) -> float:
        if not self.basket_positions:
            return round(self.initial_volume, 2)
        last_vol = self.basket_positions[-1]["volume"]
        next_vol = last_vol * self.volume_multiplier
        return round(max(next_vol, 0.01), 2)

    # --- Public API --------------------------------------------------
    def open_basket(self, direction: str, price: float, ticket: int = 0) -> Dict:
        self.basket_open = True
        self.basket_direction = direction
        self.basket_positions = [{"price": price, "volume": round(self.initial_volume, 2), "ticket": ticket}]
        self.mfe_profit = 0.0
        self.best_price = price
        self._be_armed = False
        self._resume_grace_remaining = 0
        self._ticks_open = 0
        self._skip_marti_stop = False
        self.logger.info("Opened %s basket @ %.5f vol=%.2f", direction, price, self.initial_volume)
        return {
            "action": "OPEN",
            "direction": direction,
            "price": price,
            "volume": round(self.initial_volume, 2),
            "basket_size": 1,
        }

    def should_add_to_basket(self, current_price: float) -> bool:
        if not self.basket_open or not self.basket_positions:
            return False

        if len(self.basket_positions) >= self.max_positions:
            return False

        total_vol = sum(p["volume"] for p in self.basket_positions)
        if total_vol >= self.max_total_volume:
            return False

        last_entry = self.basket_positions[-1]["price"]
        if self.basket_direction == "BUY":
            pip_move = (current_price - last_entry) * self.pip_multiplier
        else:
            pip_move = (last_entry - current_price) * self.pip_multiplier

        return pip_move >= self.add_distance_pips

    def add_to_basket(self, price: float, ticket: int = 0) -> Dict:
        volume = self._compute_next_volume()
        self.basket_positions.append({"price": price, "volume": volume, "ticket": ticket})
        total_vol = sum(p["volume"] for p in self.basket_positions)
        self.logger.info("Added %s @ %.5f vol=%.2f total=%.2f", self.basket_direction, price, volume, total_vol)
        return {
            "action": "ADD",
            "direction": self.basket_direction,
            "price": price,
            "volume": volume,
            "basket_size": len(self.basket_positions),
            "total_volume": total_vol,
        }

    def should_close_basket(self, current_price: float, atr_pips: Optional[float] = None) -> Tuple[bool, str]:
        if not self.basket_open:
            return False, ""

        self._ticks_open += 1
        if self._resume_grace_remaining > 0:
            self._resume_grace_remaining -= 1
            return False, ""

        current_profit = self._current_profit(current_price)
        self._update_mfe(current_profit)
        self._arm_breakeven_if_ready(current_profit)
        total_vol = sum(p["volume"] for p in self.basket_positions)

        # Marti-style mirrored SL/TP based on profit_per_lot × total_volume
        marti_stop = total_vol * self.marti_profit_per_lot
        if not self._skip_marti_stop:
            if marti_stop > 0 and current_profit <= -marti_stop:
                return True, "MARTI_STOP"
            marti_tp = marti_stop * self.marti_tp_multiple
            if marti_tp > 0 and current_profit >= marti_tp:
                return True, "MARTI_TP"

        # Optional tiny hard stop (extra failsafe)
        if self.hard_stop_dollars > 0 and current_profit <= -self.hard_stop_dollars:
            return True, "HARD_STOP"

        # Breakeven ratchet once armed
        if self._be_armed and self.basket_positions:
            wbe = self._weighted_entry()
            buffer_price = self.be_buffer_pips / self.pip_multiplier
            be_stop = wbe - buffer_price if self.basket_direction == "BUY" else wbe + buffer_price
            if self.basket_direction == "BUY" and current_price <= be_stop:
                return True, "BE_STOP"
            if self.basket_direction == "SELL" and current_price >= be_stop:
                return True, "BE_STOP"

        # ATR-based trail (optional)
        if self.trail_atr_k > 0 and atr_pips is not None:
            atr_price = (atr_pips * self.trail_atr_k) / self.pip_multiplier
            if self.best_price is not None:
                if self.basket_direction == "BUY":
                    trail_price = self.best_price - atr_price
                    if current_price < trail_price:
                        return True, "ATR_TRAIL"
                else:
                    trail_price = self.best_price + atr_price
                    if current_price > trail_price:
                        return True, "ATR_TRAIL"

        # Profit giveback trail with dynamic start based on basket size
        if self.trail_enabled and self._ticks_open >= self.min_ticks_for_trail:
            trail_floor = max(self.trail_min_profit, 0.0)
            if marti_stop > 0 and self.trail_start_multiple > 0:
                trail_floor = max(trail_floor, marti_stop * self.trail_start_multiple)
            if self.mfe_profit > trail_floor:
                threshold = self.mfe_profit * (1 - self.trail_giveback_pct)
                if current_profit <= threshold:
                    return True, "TRAIL_GIVEBACK"

        # Track best price for trailing
        if self.best_price is None:
            self.best_price = current_price
        else:
            if self.basket_direction == "BUY":
                self.best_price = max(self.best_price, current_price)
            else:
                self.best_price = min(self.best_price, current_price)

        return False, ""

    def close_basket(self, current_price: float, reason: str) -> Dict:
        final_profit = self._current_profit(current_price)
        basket_size = len(self.basket_positions)
        total_volume = sum(p["volume"] for p in self.basket_positions)
        direction = self.basket_direction

        self.basket_open = False
        self.basket_direction = None
        self.basket_positions = []
        self.mfe_profit = 0.0
        self.best_price = None
        self._be_armed = False

        self.logger.info(
            "Closed %s basket (%s): size=%d vol=%.2f PnL=$%.2f",
            direction,
            reason,
            basket_size,
            total_volume,
            final_profit,
        )
        return {
            "action": "CLOSE",
            "direction": direction,
            "basket_size": basket_size,
            "total_volume": total_volume,
            "profit": final_profit,
            "reason": reason,
        }

    def get_status(self) -> Dict:
        if not self.basket_open:
            return {"basket_open": False}
        total_volume = sum(p["volume"] for p in self.basket_positions)
        return {
            "basket_open": True,
            "direction": self.basket_direction,
            "basket_size": len(self.basket_positions),
            "total_volume": total_volume,
            "positions": self.basket_positions.copy(),
            "mfe_profit": round(self.mfe_profit, 2),
            "_be_armed": self._be_armed,
        }

    def mark_synced_from_mt5(self):
        """Apply a short grace period after syncing pre-existing baskets to avoid immediate closes."""
        self._resume_grace_remaining = max(self.resume_grace_ticks, 0)
        self._ticks_open = 0

    def mark_inherited(self, skip_marti_stop: bool = False):
        self._skip_marti_stop = skip_marti_stop
        # Do not keep previous BE state on inherited baskets
        self._be_armed = False
