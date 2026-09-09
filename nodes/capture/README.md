# capture

**Kind:** `sink` (writer) + `source` (reader)
**Implements:** `capture.py`

Raw WebSocket frames to disk, **before** they are parsed. One gzip JSONL file per venue per hour
under `/Volumes/Kilos/janus/frames/<venue>/<YYYY-MM-DD>/<HH>.jsonl.gz`; each line is
`{"t": received_utc, "m": received_mono, "raw": "<frame text>"}`.

## Position in the grid

```
[stream_kalshi] ──▶ recv ──▶ [capture.FrameWriter] ──▶ disk ──▶ [replay] ──▶ the same handle()
[stream_polymarket] ┘   └──▶ handle()   (capture never sits between recv and handle's result)
```

**Upstream:** the two stream nodes, which call `write(raw)` on every received frame when a writer
is attached. **Downstream:** `nodes/replay`, the reconnect/gap battery, the slippage measurement.

## Contract

`FrameWriter(venue, root)` — `write(raw, received_utc=, received_mono=)`, `flush()`, `close()`,
`stats()`. `read_frames(path)`, `capture_files(root, venue, start, end)`, `iter_capture(...)`,
`merge(streams)` (by receive time, stable within a venue).

## Failure modes

**Capture before parse, never after.** A parse bug is the thing you most want to replay. The
writer takes the text the socket delivered; a frame that is not valid JSON is still captured.

**Buffered.** gzip buffers; a hard kill loses the unflushed tail. The supervisor flushes on its
report tick. The hour boundary closes and reopens the file, so at most one hour is ever open.

**Volume.** Polymarket `book` events carry full ladders; measure a day before fixing retention.
The writer refuses any root outside `/Volumes/Kilos`.

**Compression CPU.** Capture uses gzip level 3. L51's bounded offline sample of
10,000 raw frames per venue retained every frame, timestamp and ordering exactly,
used about 59% less compression CPU than level 9, and increased file size by
25% on Polymarket and 34% on Kalshi. Existing level-9 members remain readable and
new members may append to the same hour. This is a capture-cost measurement;
it does not establish a live CPU or socket-health improvement. See
`research/infra/2026-09-09_live-cpu-health/` for measurements and limitations.

## Tests

`tests/test_capture.py` — round trip byte-for-byte, non-JSON frames kept, hour rotation, the
volume guard, the merge order.
