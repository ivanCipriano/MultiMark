"""«Cambio di forma = stesso output» (§2 P1, criteri di accettazione; casi limite di §3.3.1b).

Per ogni frammento con un ``main`` eseguibile: si invertono i siti uno alla volta e tutti insieme
(``rewrite.write_structural``), si esegue ogni versione in un processo separato (timeout 5 s,
senza sandbox: sono frammenti scritti da noi) e l'output deve coincidere con quello dell'originale.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from multimark._astindex import AstIndex
from multimark.channels import CHANNELS, ReadOptions
from multimark.rewrite import WriteRequest, write_structural
from multimark.sites import find_sites

FRAGMENTS: dict[str, str] = {
    "aug_assign": """
        def main():
            x = 10
            x = x + 1
            x -= 2.5
            y = 7
            y = y / 2
            y //= 2
            z = 17
            z = z % 5
            z **= 3
            w = 2
            w = w ** (1 + 1)
            print(x, y, z, w)
        """,
    "compare_dir": """
        class P:
            v = 3
        def main():
            p = P()
            xs = [1, 2, 3]
            print(2 < p.v, p.v >= 3, xs[0] > 0, len(xs) <= 2, -1 < p.v, 1.5 > p.v)
        """,
    "equality_dir": """
        def main():
            s = "a"
            xs = [1]
            print(s == "a", "b" != s, xs[0] == 1, 2 != len(xs), s.upper() == "A")
        """,
    "list_comp": """
        def main():
            data = [3, 1, 2]
            out = []
            for v in data:
                out.append(v * v + 1)
            sq = [str(w) for w in range(4)]
            print(out, sq)
        """,
    "ternary": """
        def main():
            for k in (0, 1, 2):
                if k > 1:
                    label = "big"
                else:
                    label = "small"
                tag = (k, 1) if k else (0, 0)
                print(label, tag)
        """,
    "operand_order": """
        def main():
            n = 4
            s = "ab"
            xs = [1, 2]
            f = 0.1
            print(n + 1, 2 * n, s * 3, 2 * xs, f + 0.2, 3.0 * f)
        """,
    "empty_coll": """
        def main():
            a = []
            b = {}
            c = list()
            d = dict()
            a.append(1)
            b["k"] = 2
            print(a, b, c, d, type(c).__name__, type(d).__name__)
        """,
    "none_check": """
        def main():
            for v in (None, 0, "", [1]):
                print(v is None, v is not None, v == None, v != None)
        """,
    "range_zero": """
        def main():
            n = 5
            print(list(range(0, n)), list(range(n)), sum(range(0, 3)), list(range(0, -2)))
        """,
    "slice_lower": """
        def main():
            xs = [1, 2, 3, 4]
            s = "hello"
            ys = list(xs)
            ys[0:2] = [9, 9]
            print(xs[0:2], xs[:3], xs[0:], s[:2], s[0:4], ys, xs[:])
        """,
    "else_return": """
        def classify(c, d):
            if c > 2:
                return "big"
            x = c * 2
            if d:
                return "flag"
            return x

        def scan(items):
            out = []
            for it in items:
                if it < 0:
                    continue
                out.append(it)
                if it > 5:
                    break
            return out

        def check(v):
            try:
                if v is None:
                    raise ValueError("none")
                else:
                    return v + 1
            except ValueError as exc:
                return str(exc)

        def main():
            print(classify(3, 0), classify(1, 1), classify(1, 0))
            print(scan([1, -2, 7, 3]), check(None), check(2))
        """,
    "nested_if": """
        calls = []

        def f(v):
            calls.append(("f", v))
            return v

        def g(v):
            calls.append(("g", v))
            return v

        def main():
            for a in (0, 1):
                for b in (0, 1):
                    if f(a):
                        if g(b):
                            calls.append("body")
                    if f(a) and g(b) and a:
                        calls.append("body2")
                    if a:
                        if b:
                            if a + b:
                                calls.append("three")
            print(calls)
        """,
    "square": """
        class O:
            v = 1.1
        def main():
            o = O()
            xs = []
            for x in (3, -2, 0.1, 1e154, -0.0, 7.25):
                xs.append((x * x, x ** 2, -x ** 2, 10 / x ** 2 if x else 0))
            print(xs, o.v * o.v, o.v ** 2)
        """,
    "return_none": """
        def a(flag):
            if flag:
                return None
            return

        def gen():
            yield 1
            return None

        def main():
            print(a(True), a(False), list(gen()))
        """,
}


def _run(code: str) -> str:
    source = code + "\n\nif __name__ == '__main__':\n    main()\n"
    proc = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.mark.parametrize("channel", list(FRAGMENTS))
def test_form_change_keeps_output(channel: str) -> None:
    code = textwrap.dedent(FRAGMENTS[channel]).lstrip("\n")
    index = AstIndex.from_code(code)
    sites = find_sites(index, ReadOptions())
    target_sites = [s for s in sites if s.channel == channel]
    assert target_sites, f"fragment for {channel} has no {channel} sites"
    expected = _run(code)
    variants = [[WriteRequest(s, 1 - s.value)] for s in sites]
    variants.append([WriteRequest(s, 1 - s.value) for s in sites])
    for requests in variants:
        new, unwritable = write_structural(code, index, requests)
        assert not unwritable
        assert _run(new) == expected, new


def test_every_channel_has_an_execution_fragment() -> None:
    assert set(FRAGMENTS) == set(CHANNELS)


def test_square_float_values_are_identical() -> None:
    # §3.3.1b: x*x e x**2 coincidono su CPython per questi float (si misura e si riporta).
    for x in (0.1, 1.1, 7.25, -3.3, 1e154, 2.0**0.5):
        assert x * x == x**2
