"""Refuses a pattern that could take exponential time, by running it and watching the clock.

A backtracking regex engine cannot be interrupted from inside, in Python or in Java. So the
pattern is tried in a child process against inputs built to make it work as hard as it can, and
the child is killed if it is still going at the deadline. This module is both halves: the parent
(`SubprocessPatternProbe`) and, run with `python -m`, the child.

# ponytail: the inputs are a heuristic. A pattern that only blows up on an input not generated
# here gets through, to be stopped by Cancel or the job's time limit. Deriving attack strings
# from the pattern's automaton is the upgrade, if that ever happens in practice.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from domain.errors import UnsafePattern

# One input may take this long. A linear pattern needs microseconds, and a quadratic one such as
# \s+$ (harmless on real cells) a few hundredths of a second. Cubic and worse run far past it.
PER_INPUT_SECONDS = 0.25
# All inputs together. It bounds a pattern that is merely slow on everything.
TOTAL_SECONDS = 1.5
# Then the child is killed, whatever it is doing.
DEADLINE_SECONDS = 2.0

# Exponential blow-up shows within a few dozen characters, polynomial only on long input. At
# 2,000 characters a quadratic pattern costs a few million steps and a cubic one several billion,
# which keeps both far from the per-input budget, on opposite sides, on a slow machine too.
_SHORT, _LONG = 32, 2000
_PUNCTUATION = "@.-_/:,;#+ "
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def pump_strings(pattern: str) -> list[str]:
    """Long runs of the characters the pattern is about, each with an ending that spoils the match.

    Catastrophic backtracking needs a run the pattern can split in many ways, followed by
    something that makes every split fail: (a+)+$ on "aaaa...a!". The runs here repeat the
    pattern's own literal characters, one stand-in for each character class, and pairs of them,
    for patterns such as (\\w+\\s?)* whose repeated unit is two kinds of character.
    """
    own = [c for c in dict.fromkeys(pattern) if c.isalnum() or c in _PUNCTUATION]
    atoms = list(dict.fromkeys(["a", "1", " ", *own]))[:14]
    pairs = [first + second for first in atoms[:5] for second in atoms[:5] if first != second]
    units = atoms + pairs
    strings = []
    for unit in units:
        short, long = unit * (_SHORT // len(unit)), unit * (_LONG // len(unit))
        # "!" spoils a match that must reach the end; the line break also stops a trailing ".*".
        strings += [short + "!", short + "\n!", long + "!"]
    return strings


class SubprocessPatternProbe:
    def check(self, pattern: str) -> None:
        strings = pump_strings(pattern)
        try:
            finished = subprocess.run(
                # A child through subprocess, not multiprocessing: Celery's pool processes are
                # daemonic, and those may not have multiprocessing children.
                [sys.executable, "-m", "infrastructure.pattern_probe"],
                input=json.dumps({"pattern": pattern, "strings": strings}),
                capture_output=True,
                text=True,
                cwd=_BACKEND_ROOT,
                timeout=DEADLINE_SECONDS,
            )
            reports = finished.stdout.splitlines()
        except subprocess.TimeoutExpired as hung:  # run() has killed the child by now
            output = hung.stdout or b""
            reports = (output.decode() if isinstance(output, bytes) else output).splitlines()
            raise UnsafePattern(_explain(strings, reports, "did not finish")) from None

        if not reports or reports[-1] != "ok":
            raise UnsafePattern(_explain(strings, reports, "took too long"))


def _explain(strings: list[str], reports: list[str], what: str) -> str:
    # The child prints the index of each input before trying it, so the last one names the culprit.
    indexes = [int(line) for line in reports if line.isdigit()]
    if not indexes:
        return f"it {what} when tried on test inputs"
    culprit = strings[indexes[-1]]
    shown = culprit if len(culprit) <= 40 else f"{culprit[:24]}... ({len(culprit)} characters)"
    return (
        f"it {what} on the input {shown!r}, which is how a pattern with nested or overlapping "
        "repetition behaves"
    )


def _run_child() -> None:
    """The child: try each input in turn, announcing it first, and stop at the first slow one."""
    job = json.load(sys.stdin)
    compiled = re.compile(job["pattern"])
    started = time.perf_counter()
    for index, text in enumerate(job["strings"]):
        print(index, flush=True)
        before = time.perf_counter()
        compiled.sub("", text)  # what the job does: find every match, from every position
        now = time.perf_counter()
        if now - before > PER_INPUT_SECONDS or now - started > TOTAL_SECONDS:
            return
    print("ok", flush=True)


if __name__ == "__main__":
    _run_child()
