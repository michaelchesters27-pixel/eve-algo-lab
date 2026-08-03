# Project Status — EVE Command Centre v3.1

## Autonomous engine

- Historical market memory remains active.
- Continuous research remains active.
- Strategy creation remains active.
- Evolution lineages and controlled mutation remain active.
- High-resolution validation remains active.
- MT5 package generation remains active.
- No worker cadence, promotion threshold or frozen trading rule was changed by the interface reorganisation.

## User experience

- Six-workspace layout is active.
- Bot Library is organised by practical usage schedule.
- Combined weekday/month/quarter/time rules receive combined labels.
- Demo Fleet is implemented with online, stale, offline, detached and duplicate states.
- Bot Library cross-links matching online MT5 packages.
- Legacy Fixed Ladder testing remains optional under Advanced.

## Operational requirement

Run `SUPABASE_UPDATE_v3.1.sql` once, then replace older attached EAs with newly downloaded fleet-ready builds to gain automatic attachment detection.

## Known boundary

The build environment cannot run MetaEditor. Fleet-ready MQL5 source is statically validated and covered by generator tests, but each downloaded `.mq5` must still be compiled in MetaEditor before use.
