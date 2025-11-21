"""
Lightweight MT5 helper for the flipped XU ML bot.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import MetaTrader5 as mt5


logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    ticket: int
    price: float


class MT5Client:
    def __init__(self, symbol: str, magic_number: int, slippage_points: int = 100, comment: str = ""):
        self.symbol = symbol
        self.magic_number = int(magic_number)
        self.slippage_points = slippage_points
        self.comment = comment

    @staticmethod
    def connect(login: int, password: str, server: str, path: Optional[str] = None):
        if not mt5.initialize(path=path):
            raise RuntimeError(f"Failed to initialize MT5: {mt5.last_error()}")
        if not mt5.login(login=login, password=password, server=server):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
        logger.info("MT5 login OK (account %s @ %s)", login, server)

    def latest_tick(self):
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise RuntimeError(f"Could not fetch tick for {self.symbol}: {mt5.last_error()}")
        return tick

    def copy_rates(self, timeframe, count: int = 300):
        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
        if rates is None:
            raise RuntimeError(f"Could not fetch rates for {self.symbol}: {mt5.last_error()}")
        return rates

    def open_market(self, direction: str, volume: float, comment: Optional[str] = None) -> OrderResult:
        tick = self.latest_tick()
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if direction == "BUY" else tick.bid
        trade_comment = comment if comment is not None else self.comment
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": self.slippage_points,
            "magic": self.magic_number,
            "comment": trade_comment,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"Order send failed: {result}")
        logger.info("Opened %s %.2f @ %.5f ticket=%s", direction, volume, result.price, result.order)
        return OrderResult(ticket=result.order, price=result.price)

    def close_position(self, position) -> OrderResult:
        direction = "SELL" if position.type == mt5.POSITION_TYPE_BUY else "BUY"
        tick = self.latest_tick()
        price = tick.bid if direction == "SELL" else tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": position.ticket,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": mt5.ORDER_TYPE_SELL if direction == "SELL" else mt5.ORDER_TYPE_BUY,
            "price": price,
            "deviation": self.slippage_points,
            "magic": self.magic_number,
            "comment": f"close {self.comment}".strip(),
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"Close failed for ticket {position.ticket}: {result}")
        logger.info("Closed position %s @ %.5f", position.ticket, result.price)
        return OrderResult(ticket=result.order, price=result.price)

    def close_all(self, tickets: Optional[List[int]] = None) -> List[OrderResult]:
        positions = self.positions()
        if tickets:
            positions = [p for p in positions if p.ticket in tickets]
        closed: List[OrderResult] = []
        for pos in positions:
            try:
                closed.append(self.close_position(pos))
            except Exception as exc:
                logger.error("Close failure for ticket %s: %s", pos.ticket, exc)
        return closed

    def positions(self):
        positions = mt5.positions_get(symbol=self.symbol, magic=self.magic_number)
        return positions or []
