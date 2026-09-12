# L81 verdict — ladder memo, per-side rebuild, capture off the loop, decode

Offline (L78 instrument 2): the ladder changes alone measured 10.53 s against L79's 10.11 s
(within noise at this slate: the instrument decodes frames itself and runs no capture writer, so
two of the three targets are invisible to it); with L80 the joint tree measures 3.80 s. The
per-side `project_in` shortcut exists because a delta on one Kalshi ladder changes both outcome
projections, so an outcome-level key never matched. The capture writer thread's first version
deadlocked on hourly rotation (`close()` joined the queue from the drain thread); the file close
is separate now and the rotation test crosses an hour. The websocket options and the optional
orjson decoder can only be measured live (L82).
