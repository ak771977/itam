# Session Notes for Agents (Flipped Grid Project)

This is a handoff document so any agent can resume work in this `/home/marshalladmin/itam` folder without re-reading the other repo.

## What’s here
- `src/flipped_strategy.py`: Flipped grid logic (adds on favorable movement, BE ratchet, trailing exits).
- `src/risk_manager.py`: Lightweight daily loss/drawdown guard.
- `config/config.json`: Default parameters for spacing, sizing, stop/BE/trailing.
- `README.md`: User-facing blueprint and integration sketch.

## Intent (immutables to preserve)
- Keep entry logic external/unchanged. Only exit/add math is inverted.
- Adds happen **only on favorable price steps** (pyramiding into strength).
- Hard stop is **tiny**; after first add (or profit threshold), stop ratchets to **breakeven + buffer**.
- Exit via **trailing giveback** (MFE-based, optional ATR trail). No fixed TP.
- Sizing is **shallow** (flat or ~1.0–1.2×) with caps on positions/total volume to avoid margin blowups.

## Parameter defaults (config/config.json)
- `add_distance_pips`: 5 (EU) / 200 (XAU) — same noise filter as the legacy grid but applied to favorable moves.
- `volume_multiplier`: 1.1 (keep sizing convex but mild).
- `max_positions`: 6, `max_total_volume`: 2.0 (tune per symbol).
- `hard_stop_dollars`: 10.0 — “fail fast” basket loss cap.
- `be_buffer_pips`: 1.0 — spread/fee buffer around BE once armed.
- `trail_giveback_pct`: 0.4 — close if profit gives back 40% from MFE.
- `trail_atr_k`: 0.0 (ATR trail off by default; set 0.5–1.0 to enable).
- `arm_after_add`: true — BE arms after the first add; `arm_profit_dollars` can arm via profit.
- Account guards: `max_drawdown_percent` (strategy), `daily_loss_limit_percent` (risk_manager).

## Mechanics in `flipped_strategy.py`
- On `open_basket`: state reset; tiny hard stop active.
- `should_add_to_basket`: checks favorable pip move vs `add_distance_pips`, and caps (`max_positions`, `max_total_volume`).
- `should_close_basket`: evaluates in order:
  1) hard-stop dollars (fail fast),
  2) BE stop once armed (VWAP ± `be_buffer_pips`),
  3) ATR trail if configured,
  4) MFE giveback: close if `current_profit <= mfe * (1 - trail_giveback_pct)`.
  Tracks `mfe_profit` and `best_price` for trailing.
- `close_basket`: resets state; logs outcome.

## Integration sketch
- User supplies entries; agent must not change entry model.
- Runner loop per tick:
  - If basket open: call `should_close_basket(price, atr_pips)` → on True, call `close_basket`.
  - Else: if `should_add_to_basket(price)` → `add_to_basket`.
  - Entries triggered externally: guard with `RiskManager.can_open_position(account_info)`, then `open_basket`.
- `RiskManager`: call `update_daily(pnl)` and `can_open_position(account_info)` before opening.

## If more work is requested
- Calibrate params per symbol/timeframe via backtests (same entry stream, swapped exit logic).
- Add logging hooks or metrics (MFE, giveback events) if needed for tuning.
- If asked to port to another language/runner, preserve the invariants above.

## Cautions
- Don’t reintroduce averaging down; adds must remain favorable.
- Keep BE buffer ≥ spread to avoid cost bleed.
- Keep multipliers shallow; profit should come from distance, not leverage.
