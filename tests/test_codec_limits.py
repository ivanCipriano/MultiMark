"""Limiti della decodifica per cancellazioni con voti sbagliati (§3.8 [v1.2.2], MD18).

``e`` = bit decisi dal voto ma sbagliati, ``f`` = bit cancellati, all'ingresso del decodificatore.
La decodifica non corregge errori: con ``e > 0`` può restituire un messaggio sbagliato quando una
parola di codice a distanza ``<= e + f`` concorda con i bit noti.

- matrice ``random`` (``mcss``): distanza minima 2 (riga di parità del bit 12 di peso 1); garanzia:
  con ``e = 0`` mai un messaggio sbagliato;
- matrice ``dmin4`` (``multimark``): distanza minima 4; garanzie: con ``f <= 3`` la decodifica
  riesce sempre, con ``e + f <= 3`` mai un messaggio sbagliato, con ``e = 0`` mai.
"""

from __future__ import annotations

import itertools
import random

import pytest

from multimark.codec import (
    ERASURE,
    decode_erasures,
    dmin4_candidates,
    encode,
    matrix_digest,
    parity_matrix,
)
from multimark.codec_check import adopt_dmin4, analyse, classify, columns, minimum_distance

T = 2
DMIN4_24_2_SHA256 = "37732f1e4421fc6ec83a732397eb4892a4293be0bab4b000014795160cadb333"


def test_minimum_distances() -> None:
    assert minimum_distance(24, T, "random") == 2
    assert parity_matrix(24, T)[12] == [0, 0, 0, 0, 1, 0, 0, 0]
    assert minimum_distance(24, T, "dmin4") == 4


def test_dmin4_matrix_construction() -> None:
    assert matrix_digest(24, T, "dmin4") == DMIN4_24_2_SHA256
    pool = dmin4_candidates(8)
    assert len(pool) == 120 and pool == sorted(pool)
    rows = [tuple(r) for r in parity_matrix(24, T, "dmin4")]
    assert len(set(rows)) == 24
    assert all(r in pool and sum(r) % 2 == 1 and sum(r) >= 3 for r in rows)
    assert parity_matrix(24, 0, "dmin4") == [[] for _ in range(24)]
    with pytest.raises(NotImplementedError):
        parity_matrix(24, 8, "dmin4")
    with pytest.raises(ValueError):
        parity_matrix(24, T, "other")


def test_case_424242_decoder_input() -> None:
    # Ingresso del decodificatore nel caso del selftest (frammento 424242, 23 istruzioni,
    # chiave 33782, matrice casuale): e = 1 (posizione 30), f = 6.
    msg = [random.Random(33782).getrandbits(1) for _ in range(24)]
    tally = encode(msg, T)
    tally[30] ^= 1
    for i in (0, 1, 3, 5, 6, 7):
        tally[i] = ERASURE
    decoded, status = decode_erasures(tally, 24, T)
    assert status == "ok" and decoded is not None and decoded != msg
    assert "".join(map(str, decoded)) == "101011111111111111111111"


def test_random_matrix_wrong_message_with_e1_f1() -> None:
    # Con la matrice casuale: e = 1 (bit 12) e f = 1 (bit di parità 28) bastano.
    tally = encode([0] * 24, T)
    tally[12] = 1
    tally[28] = ERASURE
    decoded, status = decode_erasures(tally, 24, T)
    assert status == "ok" and decoded == [int(i == 12) for i in range(24)]
    tally = encode([0] * 24, T, "dmin4")
    tally[12] = 1
    tally[28] = ERASURE
    assert decode_erasures(tally, 24, T, "dmin4")[0] is None


def test_dmin4_up_to_three_erasures_always_decode() -> None:
    msg = [random.Random(1).getrandbits(1) for _ in range(24)]
    cw = encode(msg, T, "dmin4")
    for f in range(4):
        for erased in itertools.combinations(range(32), f):
            tally = list(cw)
            for i in erased:
                tally[i] = ERASURE
            assert decode_erasures(tally, 24, T, "dmin4") == (msg, "ok"), erased


def test_dmin4_never_wrong_with_e_plus_f_at_most_3() -> None:
    msg = [random.Random(2).getrandbits(1) for _ in range(24)]
    cw = encode(msg, T, "dmin4")
    for e in (1, 2, 3):
        for f in range(0, 4 - e):
            for positions in itertools.combinations(range(32), e + f):
                for wrong in itertools.combinations(positions, e):
                    tally = list(cw)
                    for i in positions:
                        tally[i] = (cw[i] ^ 1) if i in wrong else ERASURE
                    decoded, _ = decode_erasures(tally, 24, T, "dmin4")
                    assert decoded is None, (wrong, positions)


@pytest.mark.parametrize("matrix", ["random", "dmin4"])
def test_no_wrong_message_without_errors(matrix: str) -> None:
    rng = random.Random(5)
    for _ in range(400):
        msg = [rng.getrandbits(1) for _ in range(24)]
        tally = encode(msg, T, matrix)
        for i in rng.sample(range(32), rng.randint(0, 12)):
            tally[i] = ERASURE
        decoded, status = decode_erasures(tally, 24, T, matrix)
        assert status in ("ok", "ambiguous") and (decoded is None or decoded == msg)


@pytest.mark.parametrize("matrix", ["random", "dmin4"])
def test_classify_matches_decoder(matrix: str) -> None:
    cols = columns(24, T, matrix)
    rng = random.Random(9)
    for _ in range(1500):
        msg = [rng.getrandbits(1) for _ in range(24)]
        cw = encode(msg, T, matrix)
        f = rng.randint(0, 8)
        positions = rng.sample(range(32), f + 1)
        erased, j = tuple(positions[:f]), positions[f] if rng.random() < 0.7 else -1
        tally = list(cw)
        for i in erased:
            tally[i] = ERASURE
        if j >= 0:
            tally[j] ^= 1
        decoded, status = decode_erasures(tally, 24, T, matrix)
        got = classify(cols, 24, erased, j)
        if got == "ok":
            assert decoded == msg
        elif got == "wrong":
            assert decoded is not None and decoded != msg
        else:
            assert decoded is None and status in ("inconsistent", "ambiguous")


def test_adoption_criterion_passes() -> None:
    r = analyse(24, T, "random", samples=2000)
    d = analyse(24, T, "dmin4", samples=2000)
    assert adopt_dmin4(r, d)
    by_f = {row.f: row for row in d}
    assert all(by_f[f].p_unique == 1.0 for f in range(4))
    assert by_f[1].p_wrong_e1 == by_f[2].p_wrong_e1 == 0.0
