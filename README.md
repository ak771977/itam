# Flipped Grid Blueprint

This folder contains a flipped version of the martingale grid:
- Adds on favorable movement (pyramiding into strength)
- Hard stop is tiny; stop ratchets to breakeven after the first add
- Exits on trailing giveback instead of a fixed TP

## Files
- `src/flipped_strategy.py` – core flipped basket logic
- `src/risk_manager.py` – simple daily-loss/drawdown guard
- `config/config.json` – tweak spacing, sizing, breakeven buffer, and trailing giveback

## How it works (math)
1. Entry logic is unchanged (plug in your signals). On first fill, a small hard-stop dollar cap is active.
2. Adds trigger only when price moves in your favor by `add_distance_pips`.
3. After the first add (or when profit exceeds `arm_profit_dollars`), the stop is armed to breakeven + `be_buffer_pips` (basket VWAP).
4. MFE is tracked; the basket closes when profit gives back `trail_giveback_pct` (or when an ATR trail is configured).
5. A hard-stop cap remains for gaps/slippage.

## Key knobs (config/config.json)
- `add_distance_pips`: favorable spacing per add (keep at/above noise).
- `volume_multiplier`: keep shallow (1.0–1.2) so margin stays light; `max_positions`/`max_total_volume` cap risk.
- `hard_stop_dollars`: tiny “fail fast” loss per basket.
- `be_buffer_pips`: spread/fee buffer around breakeven once armed.
- `trail_giveback_pct`: % of MFE you’re willing to give back (e.g., 0.35–0.5).
- `trail_atr_k`: optional ATR-based trail (0 to disable).
- `arm_after_add` / `arm_profit_dollars`: when to arm the breakeven stop.
- `max_drawdown_percent`, `daily_loss_limit_percent`: account guards via `risk_manager`.

## Integration sketch
- Instantiate `FlippedStrategy(symbol, config)` and feed the same prices you use today.
- Call `open_basket(direction, price)` when your entry model fires.
- Each tick:
  - If `should_close_basket(...)` returns True, call `close_basket(...)`.
  - Else if `should_add_to_basket(...)` returns True, call `add_to_basket(...)`.
- Run `RiskManager.can_open_position(account_info)` before opening new baskets.

## Suggested starting values
- EU: `add_distance_pips = 5`, `volume_multiplier = 1.1`, `hard_stop_dollars = 10`, `be_buffer_pips = 1`, `trail_giveback_pct = 0.4`, `max_positions = 4–6`.
- XAU: `add_distance_pips = 200`, keep the same percentages and shallow sizing.

## XU ML variant (flipped exit)
- Config: `config/config_xu_ml.json` (unique magic number, ML thresholds, logging/rotation).
- Runner: `run_xu_ml_bot.py` (Windows helper `start_xu_ml_bot.bat` boots the venv via `bootstrap_env.py --profile xu-ml`).
- Uses the same XAUUSD ML entry model as marti and manages baskets with `FlippedStrategy`.
- Marti-style guardrails: `marti_profit_per_lot` sets the mirrored SL per lot; basket closes if PnL <= -SL or if PnL >= `marti_tp_multiple` × SL. Trailing starts only after hitting a fraction of that per-lot stop so profit isn’t locked too early.

Backtest with your existing entry stream to calibrate `trail_giveback_pct` and `hard_stop_dollars` so expectancy stays positive while the left tail remains small.
