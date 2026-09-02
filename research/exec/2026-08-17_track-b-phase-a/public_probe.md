# Phase A public API probe

**Status:** M1 characterization complete; authenticated capture not started.

Measured 2026-08-17 with 27 public REST requests, zero retries and zero 429s:

- Kalshi returned **19** series with `frequency=fifteen_min`.
- **12** had an open market at the probe instant: BNB, BTC, DOGE, ETH, GOLD, HYPE, NEAR,
  SILVER, SOL, WTI, XRP, and ZEC.
- Every sampled open market used decimal-dollar pricing fields. Its `open_time` and `close_time`
  were exactly 15 minutes apart, so the sports-series `close_time = start + 3 days` convention
  does not transfer to this surface.
- Settlement-source metadata separated CF Benchmarks crypto from Pyth Gold/Silver/WTI.
- All seven current Polymarket rolling markets (BTC, ETH, SOL, XRP, DOGE, BNB, HYPE) existed at
  the deterministic Gamma slug and carried CLOB token IDs. Each sampled payload carried
  `feeSchedule={rate:0.07, exponent:1, takerOnly:true, rebateRate:0.2}`.

This probe read metadata only. It did not open the authenticated Kalshi WebSocket, read outcomes,
touch a holdout, or spend a test look.

