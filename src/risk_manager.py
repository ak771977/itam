"""
Lightweight risk guard for the flipped strategy:
- Daily loss limit
- Account-level drawdown guard
"""
from typing import Dict, Tuple
from datetime import datetime
import logging


class RiskManager:
    def __init__(self, config: dict):
        self.logger = logging.getLogger(__name__)
        rm = config.get("risk_management", {}) if config else {}
        strat = config.get("strategy", {}) if config else {}

        self.daily_loss_limit_pct = float(rm.get("daily_loss_limit_percent", 5.0))
        self.max_drawdown_pct = float(strat.get("max_drawdown_percent", 10.0))

        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset = datetime.now().date()
        self.peak_equity = 0.0

    def update_daily(self, current_pnl: float):
        today = datetime.now().date()
        if today != self.last_reset:
            self.logger.info("Daily reset: PnL=%.2f trades=%d", self.daily_pnl, self.daily_trades)
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.last_reset = today
        self.daily_pnl = current_pnl

    def can_open_position(self, account_info: Dict) -> Tuple[bool, str]:
        # Daily loss cap
        daily_loss_cap = account_info.get("balance", 0) * (self.daily_loss_limit_pct / 100)
        if self.daily_pnl <= -daily_loss_cap:
            return False, "DAILY_LOSS_LIMIT"

        equity = account_info.get("equity", account_info.get("balance", 0))
        if equity > self.peak_equity:
            self.peak_equity = equity

        if self.peak_equity > 0:
            drawdown_pct = ((self.peak_equity - equity) / self.peak_equity) * 100
            if drawdown_pct >= self.max_drawdown_pct:
                return False, "MAX_DRAWDOWN"

        return True, "OK"
