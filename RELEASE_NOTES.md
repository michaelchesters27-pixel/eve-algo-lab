# EVE Algo Lab v1.6.1

## Responsive Live Data panel fix

### Fixed

- Live XAU/USD price now scales to the actual width of the Live Data card.
- Large prices such as `4,048.43` remain on one line without clipping or overlapping.
- The right-hand Live Data card receives a safer minimum width on common desktop screens.
- REST sync badge, OHLC values and completed-bar timeframe line wrap cleanly on narrower screens.
- Very narrow screens use a one-column OHLC layout.

### Preserved

- Autonomous 15-minute learning cycles.
- Six-timeframe candle sync and historical storage.
- Existing Supabase data, learning records, research, discoveries and backtests.
- Existing Railway and Netlify variables.

### Deployment

Replace the existing GitHub repository contents with this complete build. No Supabase SQL and no variable changes are required when upgrading from v1.6.0.
