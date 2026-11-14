"""Controllo delle matrici del codice compatto (PIPELINE_metodo.md §3.8 [v1.2.2]).

Uso::

    python -m multimark.cli.codec_matrices --log docs/milestone_logs/P1_codec_matrices.txt
"""

from __future__ import annotations

import argparse
import platform
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from multimark import __version__
from multimark.codec import MATRICES, matrix_digest
from multimark.codec_check import (
    ADOPTION_F,
    ADOPTION_MARGIN,
    EXACT_MAX_F,
    adopt_dmin4,
    analyse,
    minimum_distance,
)


def report(samples: int, message_bits: int = 24, t: int = 2) -> str:
    t0 = time.perf_counter()
    rows = {m: analyse(message_bits, t, m, samples) for m in MATRICES}
    lines = [
        "P1 check of the compact-code matrices (python -m multimark.cli.codec_matrices)",
        f"library {__version__}; python {platform.python_version()}; message_bits={message_bits} "
        f"t={t} B={message_bits + 4 * t}; exact for f <= {EXACT_MAX_F}, {samples} samples above",
        "f = erasures chosen uniformly among the B positions; e = 1 wrong vote in one of the "
        "B - f remaining positions",
        "",
    ]
    for m in MATRICES:
        lines.append(f"matrix {m}: sha256 {matrix_digest(message_bits, t, m)}; minimum distance "
                     f"{minimum_distance(message_bits, t, m)}")  # fmt: skip
    lines += ["", "| f | method | P(unique) random | P(unique) dmin4 | P(wrong, e=1) random | "
              "P(wrong, e=1) dmin4 |", "|---|---|---|---|---|---|"]  # fmt: skip
    for r, d in zip(rows["random"], rows["dmin4"]):
        how = "exact" if r.exact else f"{r.n} samples"
        lines.append(f"| {r.f} | {how} | {r.p_unique:.6f} | {d.p_unique:.6f} | "
                     f"{r.p_wrong_e1:.6f} | {d.p_wrong_e1:.6f} |")  # fmt: skip
    adopt = adopt_dmin4(rows["random"], rows["dmin4"])
    lines += [
        "",
        f"adoption criterion: P(unique) of dmin4 not lower than random by more than "
        f"{ADOPTION_MARGIN} at f in {ADOPTION_F}",
        f"decision: {'dmin4 is the multimark base' if adopt else 'keep random (dmin4 ablation)'}",
        f"wall time {time.perf_counter() - t0:.0f} s",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="multimark-codec-matrices", description=__doc__.splitlines()[0]
    )
    p.add_argument("--samples", type=int, default=10**6)
    p.add_argument("--log", type=Path)
    args = p.parse_args(argv)
    text = report(args.samples)
    if args.log:
        if args.log.exists():
            raise SystemExit(f"{args.log} already exists (logs are never overwritten)")
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
