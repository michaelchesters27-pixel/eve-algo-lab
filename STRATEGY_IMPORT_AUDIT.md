# Fixed Ladder v2.61 import audit

Imported source:

```text
imported-strategies/EVE_Twelve_Data_Fixed_Ladder_v2.61.mq5
```

SHA-256:

```text
f033bc756b8a066b8fdfe780ca36fe82363b3b70c2e4dd4a15e7d57546d02da9
```

## Rules mapped into the backtester

| MT5 rule | Backtest implementation |
|---|---|
| 8 BUY STOPs and 8 SELL STOPs | `levels_per_side=8`, both sides created at every rearm |
| Anchor at current mid | Ladder anchors at the current simulated mid price |
| 3.000 spacing | `spacing_price=3.0` |
| Fixed 0.01 lot | `fixed_lot=0.01`, configurable for controlled experiments |
| Initial fallback 2.000 | `fallback_price=2.0` |
| First bullet quick cut 0.750 | First unique campaign position receives 0.750 adverse stop |
| BE trigger +1.500 | Each unprotected position is checked independently |
| BE buffer +0.150 | Protected stop is entry plus/minus 0.150 |
| Protected stop closes bullet only | Position closes without killing remaining campaign |
| Newest unprotected stop closes campaign | Remaining positions and pending orders close immediately |
| Both original ladders stay active | Opposite pending orders are not cancelled after first fill |
| Target $5.00 | Floating basket target event |
| Peak protection $4 / $1 giveback | Moving basket floor based on highest floating P/L |
| Emergency basket loss | Minimum of $5 and 1% of current balance by default |
| Immediate rearm | New fixed ladder is anchored at the campaign-close price |

## Deliberate first-release approximations

- Twelve Data M5 bars do not contain tick order.
- Historical bid/ask is reconstructed from a configurable fixed spread.
- Commission is configurable and deducted on each completed position.
- Broker freeze levels, order rejection and changing historical spread are not reconstructable from M5 OHLC.
- A candle is flagged when both extremes can make the intrabar sequence material.

These limits are displayed in the dashboard and saved with every backtest run. M1 and tick replay are required before live approval.
