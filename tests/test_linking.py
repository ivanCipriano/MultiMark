"""Legame sito → bit e maschera (§3.4–3.5, §4.1)."""

from __future__ import annotations

from multimark.linking import (
    mask,
    offset,
    permutations,
    phi_function,
    phi_positional,
    phi_single_run,
)
from multimark.prf import prf_bit, prf_int


def test_phi_function_definition() -> None:
    off = prf_int(9, "offset", "f", "2", "compare_dir") % 32
    assert offset(9, "f", 2, "compare_dir", 32) == off
    assert [phi_function(9, "f", 2, "compare_dir", r, 32) for r in range(3)] == [
        off,
        (off + 1) % 32,
        (off + 2) % 32,
    ]


def test_phi_function_depends_only_on_its_function_and_channel() -> None:
    a = phi_function(9, "f", 2, "names", 0, 32)
    assert a == phi_function(9, "f", 2, "names", 0, 32)
    others = {phi_function(9, n, p, c, 0, 32) for n, p, c in
              [("g", 2, "names"), ("f", 3, "names"), ("f", 2, "compare_dir")]}  # fmt: skip
    assert len(others | {a}) > 1


def test_phi_single_run() -> None:
    base = prf_int(9, "offset", "f", "2") % 32
    assert phi_single_run(9, "f", 2, 5, 32) == (base + 5) % 32


def test_mask_definition() -> None:
    assert mask(9, "f", 2, "aug_assign", 3) == prf_bit(9, "mask", "f", "2", "aug_assign", "3")


def test_permutations_are_permutations_and_prefix_stable() -> None:
    perms = permutations(42, 3, 32)
    assert all(sorted(p) == list(range(32)) for p in perms)
    assert permutations(42, 1, 32)[0] == perms[0]  # decisione I: il primo ciclo non dipende da N
    assert perms[0] != perms[1]
    assert permutations(43, 1, 32)[0] != perms[0]


def test_phi_positional_cycles() -> None:
    phi = phi_positional(42, 70, 32)
    assert len(phi) == 70
    assert sorted(phi[:32]) == list(range(32)) and sorted(phi[32:64]) == list(range(32))
    assert phi_positional(42, 10, 32) == phi[:10]
    assert phi_positional(42, 0, 32) == []
