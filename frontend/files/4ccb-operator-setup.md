# 4CCB operator setup — GitHub is the source of truth

## Project rule

All 4CCB research, calibrator, validation and future bot changes are made in `michaelchesters27-pixel/eve-algo-lab` first. GitHub `main` is the canonical source. Any file downloaded into MT5 is only a deployed copy of the version stored in GitHub.

Do not edit the MT5 copy by hand. If a change is needed, change it in GitHub, verify it, then replace the MT5 copy from the canonical GitHub version.

## Current broker calibrator

Canonical source:

`mt5/EVE_4CCB_IC_Broker_Calibrator.mq5`

Purpose: read-only IC Markets XAUUSD broker telemetry for the frozen 4CCB candidate. It does not place, modify or close trades.

Telemetry endpoint:

`https://evealgolab.netlify.app/api/research/4ccb-broker-calibration/sample`

Status endpoint:

`https://evealgolab.netlify.app/api/research/4ccb-broker-calibration/status`

## Operator steps

1. From GitHub `main`, obtain `mt5/EVE_4CCB_IC_Broker_Calibrator.mq5`.
2. In IC Markets MT5 choose `File > Open Data Folder`.
3. Copy the canonical `.mq5` file into `MQL5/Experts`.
4. Open MetaEditor with F4, open the calibrator and compile with F7.
5. Require `0 errors` before continuing.
6. In MT5 choose `Tools > Options > Expert Advisors`.
7. Enable `Allow WebRequest for listed URL` and add `https://evealgolab.netlify.app`.
8. Open the broker's XAUUSD/Gold chart and attach `EVE_4CCB_IC_Broker_Calibrator`.
9. Leave telemetry enabled. It samples broker/symbol information approximately every 30 seconds.
10. Confirm EVE calibration status changes from `waiting_for_mt5` to `collecting`.

## What EVE records

- broker company/server and account currency/trade mode
- XAUUSD bid/ask and spread
- digits and point
- tick size and tick values
- contract size
- minimum/step/maximum volume
- stops level
- floating-spread flag
- long/short swap
- server UTC offset

EVE then calculates spread minimum, median, P75, P90, P95 and maximum from the collected samples.

## Gate 7

The frozen trading strategy is not changed during broker calibration or shadow forward testing. No real-money approval is implied by historical backtests or broker telemetry.