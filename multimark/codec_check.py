"""Controllo delle matrici del codice compatto prima di adottare ``dmin4`` (§3.8 [v1.2.2]).

Per ``f`` cancellazioni scelte a caso fra le ``B`` posizioni (e, per gli errori, un voto sbagliato
in una delle ``B − f`` posizioni rimaste) si calcolano, con le colonne di ``H = [Pᵀ | I]``:

- **decodifica unica**: le colonne cancellate sono linearmente indipendenti (rango ``f``); è
  l'esito ``ok`` di ``codec.decode_erasures`` con ``e = 0``;
- **messaggio sbagliato con e = 1** (errore in posizione ``j``): le colonne cancellate sono
  indipendenti e la colonna ``j`` sta nel loro spazio. La soluzione allora è unica ed è
  ``cw + e_j + e_S`` (``S`` = cancellazioni che rappresentano la colonna ``j``); il messaggio è
  sbagliato se ``{j} ∪ S`` tocca un bit del messaggio. Se la colonna ``j`` non sta nello spazio,
  l'esito è ``inconsistent``; se le cancellate sono dipendenti, nessun messaggio.

Enumerazione esatta per ``f ≤ 5``, ``samples`` campioni per ``6 ≤ f ≤ 8`` (seme fisso).
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from math import comb
from typing import Optional

from multimark.codec import _seed, codeword_length, parity_matrix

EXACT_MAX_F = 5
SAMPLED_F = (6, 7, 8)
ADOPTION_F = (4, 5)
ADOPTION_MARGIN = 0.02
_SAMPLE_LABEL = b"multimark-codec-matrices-check-v1"


def columns(message_bits: int, t: int, matrix: str) -> list[int]:
    """Colonne di ``H`` come interi di ``4t`` bit (bit ``j`` = parità ``j``)."""
    rows = parity_matrix(message_bits, t, matrix)
    cols = [sum(bit << j for j, bit in enumerate(row)) for row in rows]
    return cols + [1 << j for j in range(4 * t)]


def _basis(cols: list[int], erased: tuple[int, ...]) -> Optional[dict[int, tuple[int, int]]]:
    """Base a scala (bit di testa → (vettore, insieme di posizioni)); ``None`` se dipendenti."""
    basis: dict[int, tuple[int, int]] = {}
    for pos in erased:
        vec, used = cols[pos], 1 << pos
        while vec:
            lead = vec.bit_length() - 1
            if lead not in basis:
                break
            bvec, bused = basis[lead]
            vec ^= bvec
            used ^= bused
        if not vec:
            return None
        basis[vec.bit_length() - 1] = (vec, used)
    return basis


def _represent(basis: dict[int, tuple[int, int]], vec: int) -> Optional[int]:
    """Insieme di posizioni (bitmask) che somma a ``vec``; ``None`` se fuori dallo spazio."""
    used = 0
    while vec:
        lead = vec.bit_length() - 1
        if lead not in basis:
            return None
        bvec, bused = basis[lead]
        vec ^= bvec
        used ^= bused
    return used


def classify(cols: list[int], message_bits: int, erased: tuple[int, ...], error: int) -> str:
    """Esito della decodifica con le cancellazioni ``erased`` e un errore in ``error`` (``-1``:
    nessun errore): ``ok`` (messaggio giusto), ``wrong``, ``inconsistent``, ``ambiguous``."""
    basis = _basis(cols, erased)
    if error < 0:
        return "ambiguous" if basis is None else "ok"
    if basis is None:
        return "ambiguous_or_inconsistent"
    rep = _represent(basis, cols[error])
    if rep is None:
        return "inconsistent"
    flipped = rep | (1 << error)
    return "wrong" if flipped & ((1 << message_bits) - 1) else "ok"


@dataclass
class Row:
    f: int
    exact: bool
    p_unique: float
    p_wrong_e1: float
    n: int


def analyse(message_bits: int, t: int, matrix: str, samples: int = 10**6) -> list[Row]:
    cols = columns(message_bits, t, matrix)
    b = codeword_length(message_bits, t)
    rows: list[Row] = []
    for f in range(0, SAMPLED_F[-1] + 1):
        if f <= EXACT_MAX_F:
            unique = wrong = 0
            for erased in itertools.combinations(range(b), f):
                basis = _basis(cols, erased)
                if basis is None:
                    continue
                unique += 1
                for j in range(b):
                    if j in erased:
                        continue
                    rep = _represent(basis, cols[j])
                    if rep is not None and (rep | (1 << j)) & ((1 << message_bits) - 1):
                        wrong += 1
            n_sets = comb(b, f)
            rows.append(Row(f, True, unique / n_sets, wrong / (n_sets * (b - f)), n_sets))
            continue
        rng = random.Random(_seed(_SAMPLE_LABEL + f"|{matrix}|{f}".encode()))
        unique = wrong = 0
        for _ in range(samples):
            positions = rng.sample(range(b), f + 1)
            erased, j = tuple(positions[:f]), positions[f]
            basis = _basis(cols, erased)
            if basis is None:
                continue
            unique += 1
            rep = _represent(basis, cols[j])
            if rep is not None and (rep | (1 << j)) & ((1 << message_bits) - 1):
                wrong += 1
        rows.append(Row(f, False, unique / samples, wrong / samples, samples))
    return rows


def minimum_distance(message_bits: int, t: int, matrix: str) -> int:
    """Peso minimo delle parole di codice non nulle (enumerazione dei messaggi di peso ≤ 4)."""
    cols = columns(message_bits, t, matrix)
    best = codeword_length(message_bits, t)
    for w in range(1, 5):
        for pos in itertools.combinations(range(message_bits), w):
            syn = 0
            for p in pos:
                syn ^= cols[p]
            best = min(best, w + bin(syn).count("1"))
    return best


def adopt_dmin4(random_rows: list[Row], dmin4_rows: list[Row]) -> bool:
    """Criterio di §3.8: a f = 4 e f = 5 la decodifica unica di ``dmin4`` non è inferiore di oltre
    0,02 a quella della matrice casuale."""
    r = {row.f: row for row in random_rows}
    d = {row.f: row for row in dmin4_rows}
    return all(d[f].p_unique >= r[f].p_unique - ADOPTION_MARGIN for f in ADOPTION_F)
