# L80 verdict — one socket pulse

Offline full-pipeline replay (L78 instrument 2, 234-poller slate, 20,000 frames): with L79 and
L81 already in, adding the pulse took the median from 10.53 s to **3.80 s CPU**; evaluation rows
and selections identical. All stream, replica, poller, discovery, replay and grid suites pass
unchanged; the new pulse test covers quiet books, a stopped socket timing every replica out,
revival on the next frame, a replica registered mid-stream, and explicit heartbeats.
Live confirmation: L82 after the operator's paste.
