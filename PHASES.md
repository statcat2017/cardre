# Phase Plan — Heartbeat Watchdog

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Config + Store | Add `heartbeat_watchdog_interval_seconds` to config; add `set_active_step`/`get_active_step` to RunRepository and ProjectStore |
| 2 | Executor watchdog | Add `_HeartbeatWatchdog` context manager; wrap `node.run(ctx)` in `_execute_actions`; set/clear active step id |
| 3 | RunService enrichment | Include `active_step_id` in `RUN_RECOVERED_STALE` diagnostic |
| 4 | Backend tests | T1–T5: heartbeat advances during long step, active run not interrupted, dead run still recovered, active step diagnostics |
| 5 | Frontend stall diagnostic | Enrich stall warning with heartbeat age in `useRunProgress.ts` |
