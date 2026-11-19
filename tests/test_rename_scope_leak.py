"""Rinomina di una variabile di modulo coperta da un parametro omonimo (caso di wm-bench,
diagnosi di impercettibilità P2: mcss, codenet/p02467) e controllo ``check_renaming``."""

from __future__ import annotations

import random

import pytest

from multimark._astindex import AstIndex
from multimark.config import mcss_profile, multimark_base
from multimark.embed import embed
from multimark.names import name_sites
from multimark.rename_check import check_renaming
from multimark.rewrite import rename_variables
from multimark.sites import find_sites, loop_form_targets
from tests.helpers import src

#: Campione 7d2908b168ff (baseline): parametro ``n`` letto nel ciclo prima del riassegnamento
#: ``n //= i``, e ``n`` di modulo legato dopo la funzione.
CODE = src(
    """
    import sys


    def prime_factors(n):
        i = 2
        factors = []
        while i * i <= n:
            if n % i:
                i += 1
            else:
                n //= i
                factors.append(i)
        if n > 1:
            factors.append(n)
        return factors


    n = int(sys.stdin.readline())
    print(f"{n}: {' '.join(map(str, prime_factors(n)))}")
    """
)


#: Stesso difetto senza parametri: variabile locale ``total`` letta prima del riassegnamento
#: ``total += v`` e variabile di modulo omonima (sito con ``names.module_level=true``).
CODE_LOCAL = src(
    """
    def solve(items):
        total = 0
        for v in items:
            if total < 10:
                total += v
        return total


    data = [3, 4, 5, 6]
    total = solve(data)
    print(total)
    """
)


def _rename_all(code: str) -> str:
    """Rinomina tutte le variabili sito come ``mcss`` (parametri, modulo, una lettera estese):
    ``n`` di modulo → ``nCount``, parametro ``n`` → ``nVal``, le altre ``<nome>Zz``."""
    index = AstIndex.from_code(code)
    sites = name_sites(
        index,
        include_params=True,
        excluded_binding_ids=loop_form_targets(find_sites(index), index),
        module_level=True,
        single_letter="extend_except_loop",
    )
    new = {("", "n"): "nCount", ("prime_factors", "n"): "nVal"}
    renames = [(s, new.get((s.unit.name, s.name), s.name + "Zz")) for s in sites]
    assert {(s.unit.name, s.name) for s in sites} >= set(new)
    out, failed = rename_variables(code, index, renames)
    assert not failed
    return out


def test_module_rename_does_not_reach_shadowing_parameter() -> None:
    marked = _rename_all(CODE)
    func = marked[marked.index("def prime_factors") : marked.index("return")]
    assert "nCount" not in func, func
    result = check_renaming(CODE, marked)
    assert result.ok, result.violations


def test_marked_code_keeps_semantics() -> None:
    marked = _rename_all(CODE)
    assert check_renaming(
        CODE, marked
    ).ok  # prima dell'esecuzione: col difetto il ciclo non termina
    env: dict = {"__name__": "x"}
    exec(compile(marked.replace("int(sys.stdin.readline())", "60"), "<m>", "exec"), env)
    assert env["prime_factors"](60) == [2, 2, 3, 5]


@pytest.mark.parametrize("key", range(12))
def test_embed_mcss_keeps_scopes(key: int) -> None:
    """Inserimento completo con ``mcss`` sul campione: la variabile di modulo e il parametro
    restano distinti."""
    cfg = mcss_profile()
    r = embed(CODE, [key % 2] * cfg.message_bits, key, cfg)
    result = check_renaming(CODE, r.code)
    assert result.ok, (result.violations, r.code)


@pytest.mark.parametrize("profile", ["mcss", "multimark"])
def test_embed_local_shadowing_module(profile: str) -> None:
    """Inserimento completo con variabile locale omonima di una di modulo, su 40 chiavi e
    messaggi casuali: riguarda anche la base di ``multimark`` (``names.module_level=true``)."""
    cfg = mcss_profile() if profile == "mcss" else multimark_base()
    bad = []
    for key in range(40):
        rng = random.Random(key)
        message = [rng.randrange(2) for _ in range(cfg.message_bits)]
        r = embed(CODE_LOCAL, message, key, cfg)
        result = check_renaming(CODE_LOCAL, r.code)
        if not result.ok:
            bad.append((key, result.violations))
    assert not bad, bad[:3]


# ---------------------------------------------------------------------- il controllo da solo


def test_check_accepts_consistent_rename_and_flips() -> None:
    marked = (
        CODE.replace("(n)", "(value)").replace("i * i <= n", "value >= i * i")
        .replace("if n % i", "if value % i").replace("n //= i", "value //= i")
        .replace("if n > 1", "if 1 < value").replace("factors", "found")
        .replace("n = int", "total = int").replace("{n}", "{total}")
        .replace("prime_found(value)))", "prime_factors(total)))")
        .replace("def prime_found(value)", "def prime_factors(value)")
    )  # fmt: skip
    assert "prime_factors(total)" in marked and "def prime_factors(value)" in marked
    result = check_renaming(CODE, marked)
    assert result.ok, result.violations
    assert result.n_variables_original == result.n_variables_marked == 6  # con sys e la def
    assert result.n_unpaired_original == result.n_unpaired_marked == 0


def test_check_reports_the_wm_bench_case() -> None:
    """Il codice marcato del campione (solo le rinomine; le scritture strutturali sono a parte)."""
    marked = (
        CODE.replace("def prime_factors(n)", "def prime_factors(nVal)")
        .replace("i * i <= n:", "i * i <= nCount:").replace("if n % i", "if nCount % i")
        .replace("n //= i", "nVal //= i").replace("if n > 1", "if 1 < nVal")
        .replace("factors.append(n)", "factors.append(nVal)")
        .replace("n = int", "nCount = int").replace("{n}", "{nCount}")
        .replace("prime_factors(n)))", "prime_factors(nCount)))")
    )  # fmt: skip
    result = check_renaming(CODE, marked)
    assert not result.ok
    assert "original prime_factors:n -> marked <module>:nCount, prime_factors:nVal" in (
        result.violations
    )
    assert "marked <module>:nCount <- original <module>:n, prime_factors:n" in result.violations


def test_check_reports_swapped_variables_and_free_names() -> None:
    code = src(
        """
        def f(a, b):
            c = a - b
            return c + len(a)
        """
    )
    swapped = code.replace("c = a - b", "c = b - a")  # ``-`` non è commutativo
    assert not check_renaming(code, swapped).ok
    free = code.replace("len(a)", "size(a)")
    assert any("free name changed" in v for v in check_renaming(code, free).violations)


def test_check_global_nonlocal_and_comprehensions() -> None:
    code = src(
        """
        total = 0


        def add(x):
            global total
            total += x
            out = [x * k for k in range(3)]

            def inner():
                nonlocal out
                out = [k for k in out if k]

            inner()
            return out
        """
    )
    marked = code.replace("total", "sumVal").replace("out", "result")
    assert check_renaming(code, marked).ok
    # ``k`` della comprehension e ``k`` di un'altra comprehension restano variabili distinte
    wrong = code.replace("out = [k for k in out if k]", "out = [x for k in out if k]")
    assert not check_renaming(code, wrong).ok


def test_check_parse_error() -> None:
    result = check_renaming("x = 1\n", "x = (\n")
    assert not result.ok and result.error is not None
