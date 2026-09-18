#!/usr/bin/env bash
# F24 progress check. READ-ONLY: it reads the tuple store -- including `refusal_counts`, the
# lane's own per-tick counters -- the WHOLE kill directory (the five scopes nodes/risk/kill.py
# honours, with every other file listed as evidence), the latching daily-loss breaker state, the
# arming override and the lane's own one-second board snapshot, and changes nothing. It never
# writes /srv/janus/release-audit/f24_start_utc.
#
# The report is one JSON object of a few hundred pretty-printed lines and `row_status` sits in the
# middle of it. This is the read that enforces the $50 and 30-cover ends -- a row that is STOPPED
# (a kill file in one of the five deployed scopes, a latched breaker, the override gone/expired/
# changed, an ARM_STALE or non-LIMITED_LIVE lane, a material flag), INCONCLUSIVE (a probe that
# could not read its signal) or NEEDS_HUMAN_LOOK (the end arrived over completed UTC day(s) whose
# numbers this reader will not interpret) must not be missed in the scroll. So the last thing
# printed is a banner repeating the row's state, the numbers, what could not be looked at, and the
# verdict. The banner states facts in the report's own voice: it never says a day was blocked or
# that the lane could not trade, because the report does not say that either.
# The exit status is unchanged and is about the READER, not the row: 0 means a report was
# produced, whatever it says.
#
#   bash check_f24.sh <start_utc>              # the start_utc arm_f24.sh printed
#   bash check_f24.sh <start_utc> <end_utc>    # a fixed window (used to calibrate against L141)
#
# report.py REFUSES (exit 3) when <start_utc> disagrees by more than a second with the start
# arm_f24.sh persisted to /srv/janus/release-audit/f24_start_utc, and warns in the JSON when that
# file is absent. This script therefore does not pretty-print a refusal as if it were a report: it
# captures the reader's output, and on a non-zero exit passes it through untouched.
#
# ops/box/run.sh ignores stdin whenever it is given an argument, so report.py is embedded in the
# payload itself rather than piped alongside a command.
set -euo pipefail
START=${1:-}
END=${2:-}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
RUNNER=${F24_RUNNER:-$REPO/ops/box/run.sh}
num='^[0-9]+(\.[0-9]+)?$'
if ! [[ "$START" =~ $num ]] || { [ -n "$END" ] && ! [[ "$END" =~ $num ]]; }; then
  echo "usage: bash check_f24.sh <start_utc> [end_utc]" >&2
  exit 2
fi
if [ "$#" -gt 2 ]; then
  echo "check_f24.sh takes a start and an optional end only. --include/--exclude change WHICH" >&2
  echo "covers are scored: run report.py directly on the box so the choice is a deliberate act." >&2
  exit 2
fi

# A FIXED staging path made two simultaneous read-only checks (a progress read while another is
# already running) overwrite and then delete each other's script -- exactly the failure ops/box/run.sh
# was changed for. Each run stages its own mktemp'd file, chmod 644 so the janus user can read the
# root-owned temp file, and a trap removes ONLY that file, on every exit path. The template ends in
# the X's with no `.py` suffix: a trailing suffix is a GNU extension that BSD mktemp copies
# VERBATIM, which would hand every run the same name again on any non-GNU host. Python does not
# need the extension.
# SSM caps one command at 97 KB including the document, and report.py alone is ~114 KB, so the two
# sources travel gzipped and base64'd and are decoded on the box (the same trick the project already
# uses for oversized SSM OUTPUT -- memory: janus-box-ssm-long-jobs). mtime=0 keeps the blob byte-
# identical for identical sources, so a payload can be compared across runs.
encode_source() {
  python3 -c 'import base64, gzip, sys; sys.stdout.write(base64.b64encode(gzip.compress(sys.stdin.buffer.read(), 9, mtime=0)).decode())'
}
REPORT_B64=$(encode_source < "$HERE/report.py")

# The banner. It only re-reads fields the report already computed -- it decides nothing itself, so
# there is one source of truth for the row's state. Staged the same way as the reader, for the same
# reason, and removed by the same trap.
#
# EVERY string it prints can carry text a human or the breaker wrote: a kill file's `reason` is
# echoed verbatim into the stop lines, and an override's fields into the others. A `reason` holding
# a newline used to print a SECOND "F24_ROW_STATE:" line BELOW the real one -- and the operator
# reads the last one, so a kill file could make a stopped row read as healthy. Two independent
# defences below: `one()` flattens every printed value to a single line, so quoted text can never
# begin a line of its own; and the authoritative state line is printed LAST, after everything a
# file could have reached.
BANNER=$(cat <<'F24_BANNER_SRC'
import json
import sys

BAR = "=" * 78
#: Anything that starts a new line, or that a terminal would act on rather than show.
_BREAKS = "\r\n\v\f\x1c\x1d\x1e\x85  "


def one(value, limit=700):
    """One line, whatever the file said. Never raises: the daily read must always get a banner."""
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        flat = "".join(" / " if c in _BREAKS else (" " if ord(c) < 32 and c != "\t" else c)
                       for c in text)
        flat = " ".join(flat.split())
    except Exception as exc:                            # noqa: BLE001
        return "<unprintable: %s>" % type(exc).__name__
    return (flat[:limit] + " ...[truncated]") if len(flat) > limit else flat


def lines(obj, key):
    """A list of strings from a field that may be absent, null or the wrong shape entirely."""
    v = obj.get(key) if isinstance(obj, dict) else None
    return v if isinstance(v, list) else []


try:
    d = json.load(sys.stdin)
    if not isinstance(d, dict):
        raise ValueError("the reader printed a bare JSON %s, not a report" % type(d).__name__)
except ValueError as exc:
    print(BAR)
    print("F24_ROW_STATE: UNREADABLE -- the output above did not parse as a report (%s)" % one(exc))
    print(BAR)
    raise SystemExit(0)

def total(obj, key):
    """The sum of a {day: count} map, however malformed the field turns out to be."""
    v = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(v, dict):
        return "?"
    try:
        return sum(int(x) for x in v.values())
    except (TypeError, ValueError):
        return "?"


st = d.get("row_state") if isinstance(d.get("row_state"), dict) else {}
dr = d.get("daily_record") if isinstance(d.get("daily_record"), dict) else {}
status = one(d.get("row_status"), 60)
applied = st.get("stop_conditions_applied")
aside = "" if applied is not False else " [NOT APPLIED: a fixed end in the past was given]"
print(BAR)
print("F24_ROW_STATE: %s" % status)
print(one(d.get("headline", "")))
for line in lines(st, "stop_conditions"):
    print("  STOPPED BY%s: %s" % (aside, one(line)))
if dr:
    # Numbers. This banner names no day BLOCKED or QUIET and never says the lane could not trade:
    # the report makes no such claim, and the banner's job is to repeat the report, not to add to
    # it. `looks` are the days whose numbers a person has to read before the row gets a verdict.
    print("  LANE: %s completed UTC day(s) | %s execution(s) started | %s cover(s) settled | "
          "%s risk tick(s) recorded"
          % (one(dr.get("completed_days")), one(total(dr, "executions_started_by_utc_day")),
             one(total(dr, "covers_settled_by_utc_day")), one(dr.get("risk_ticks_over_the_row"))))
    looks = lines(dr, "days_needing_a_human_look")
    if looks:
        print("  DAY(S) NEEDING A HUMAN LOOK (no verdict is issued over them): %s"
              % one(", ".join(looks)))
        print("    %s" % one(dr.get("what_a_withheld_day_establishes", "")))
# One line per completed day, with its numbers, and the SHORT tag on the days that need an eye.
# The full sentence for each is in the warnings above, once: repeating the same paragraph seven
# times is how the one day that differs gets scrolled past.
for day in lines(dr, "days"):
    if isinstance(day, dict) and day.get("complete"):
        tags = lines(day, "look_tags")
        print("  %s: %s started, %s settled | %s | %s%s"
              % (one(day.get("utc_day"), 20), one(day.get("executions_started"), 12),
                 one(day.get("covers_settled"), 12), one(day.get("risk_line"), 320),
                 one(day.get("other_channels_line"), 160),
                 ("   <- NEEDS A HUMAN LOOK: " + one(", ".join(tags), 120)) if tags else ""))
for line in lines(d, "end_reasons"):             # already carries the applied end conditions
    print("  END: %s" % one(line))
if applied is False:
    for line in lines(st, "end_conditions"):
        print("  END%s: %s" % (aside, one(line)))
for line in lines(st, "probe_errors"):
    print("  COULD NOT LOOK: %s" % one(line))
for line in lines(st, "notes"):
    print("  NOTE: %s" % one(line))
print("  VERDICT: %s" % one(d.get("verdict")))
print("  ended=%s  conclusive=%s" % (one(d.get("ended"), 20), one(st.get("conclusive"), 20)))
print("  Only a report with ended true is F24's result. The verdict is withheld whenever a probe")
print("  could not read its signal (INCONCLUSIVE) and whenever a completed UTC day's numbers are")
print("  consistent with the lane having been unable to trade (NEEDS_HUMAN_LOOK). Neither is a")
print("  finding that it was: read the day's counts above and decide.")
print("  %d warning(s) are above, in full, under \"warnings\"." % len(lines(d, "warnings")))
print(BAR)
# LAST, and after every line that quotes something a file or a database row wrote -- a kill
# file's `reason`, an override's fields, and now a `code` straight out of refusal_counts. The
# operator reads the last F24_ROW_STATE line, so the last one has to be the report's own.
print("F24_ROW_STATE: %s   <- printed last, below every line that quotes a kill file, an" % status)
print("override or a refusal code. If a line above says a different F24_ROW_STATE, that text")
print("came out of a file or a database row, not out of this report.")
print(BAR)
F24_BANNER_SRC
)

# The box returns the report COMPRESSED, and the pretty-print and the banner run HERE.
#
# ops/box/run.sh carries SSM's ~24 KB stdout cap, and this report is far larger than that: sending
# it as text truncated it mid-object, which would have cut off the authoritative F24_ROW_STATE line
# the banner deliberately prints last. One gzip+base64 line is ~10x smaller and cannot be cut in a
# way that still decodes. Running the banner locally also takes it out of reach of anything on the
# box -- it now renders a JSON document this script decoded itself.
PAYLOAD="F24_PY=\$(mktemp /tmp/f24_report.XXXXXX)
trap 'rm -f \"\$F24_PY\"' EXIT
chmod 644 \"\$F24_PY\"
printf %s '$REPORT_B64' | base64 -d | gzip -dc > \"\$F24_PY\" || {
  echo \"check_f24: the reader could not be unpacked on the box (base64/gzip failed).\" >&2; exit 4; }
PY=/opt/janus/.venv/bin/python3
OUT=\$(sudo -u janus \$PY \"\$F24_PY\" $START $END)
rc=\$?
if [ \$rc -ne 0 ]; then
  printf '%s\n' \"\$OUT\"
  echo \"check_f24: the reader exited \$rc and produced no report (see the message above).\" >&2
  exit \$rc
fi
printf '%s' \"\$OUT\" | gzip -9 | base64 -w0 2>/dev/null || printf '%s' \"\$OUT\" | gzip -9 | base64 | tr -d '\n'
echo
exit 0"

OUT=$(bash "$RUNNER" "$PAYLOAD")
RC=$?
BLOB=$(printf '%s\n' "$OUT" | grep -Eo '^[A-Za-z0-9+/=]{200,}$' | tail -1 || true)
if [ "$RC" -ne 0 ] || [ -z "$BLOB" ]; then
  printf '%s\n' "$OUT"
  echo "check_f24: the box returned no readable report (runner exit $RC). The state is UNKNOWN:" >&2
  echo "  nothing here says the row is healthy, only that it could not be read." >&2
  exit "${RC:-3}"
fi

JSON=$(printf '%s' "$BLOB" | base64 -d | gzip -dc) || {
  echo "check_f24: the report came back but could not be decompressed." >&2; exit 3; }
printf '%s\n' "$JSON" | python3 -m json.tool || {
  echo "check_f24: the reader printed something that is not JSON." >&2; exit 3; }
printf '%s\n' "$JSON" | python3 -c "$BANNER"
exit $?
