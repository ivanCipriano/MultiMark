"""Limiti della decodifica per cancellazioni con voti sbagliati (caso 424242 del selftest).

``e`` = bit decisi dal voto ma sbagliati, ``f`` = bit cancellati, all'ingresso del decodificatore.
La decodifica non corregge errori (§3.8): con ``e > 0`` può restituire un messaggio sbagliato
quando esiste una parola di codice a distanza ``<= e + f`` che concorda con i bit noti. La nostra
matrice (MD7) ha distanza minima 2 (riga di parità del bit 12 di peso 1), quindi il limite
``2e + f <= 2t`` non basta (MD18, decisione richiesta).
"""

from __future__ import annotations

import itertools
import random

from multimark.codec import ERASURE, decode_erasures, encode, parity_matrix

T = 2


def _minimum_distance() -> int:
    best = 99
    for w in (1, 2, 3):
        for pos in itertools.combinations(range(24), w):
            m = [int(i in pos) for i in range(24)]
            best = min(best, sum(encode(m, T)))
    return best


def test_minimum_distance_is_two() -> None:
    assert _minimum_distance() == 2
    assert parity_matrix(24, T)[12] == [0, 0, 0, 0, 1, 0, 0, 0]


def test_case_424242_decoder_input() -> None:
    # Ingresso del decodificatore nel caso del selftest (frammento 424242, 23 istruzioni,
    # chiave 33782, profilo multimark): e = 1 (posizione 30), f = 6; 2e + f = 8 > 2t = 4.
    msg = [random.Random(33782).getrandbits(1) for _ in range(24)]
    cw = encode(msg, T)
    tally = list(cw)
    tally[30] ^= 1
    for i in (0, 1, 3, 5, 6, 7):
        tally[i] = ERASURE
    decoded, status = decode_erasures(tally, 24, T)
    assert status == "ok" and decoded is not None and decoded != msg
    assert "".join(map(str, decoded)) == "101011111111111111111111"


def test_wrong_message_within_2e_plus_f_le_2t() -> None:
    # Controesempio al criterio «nessun messaggio sbagliato con 2e + f <= 2t»: e = 1 (bit 12),
    # f = 1 (bit di parità 28), 2e + f = 3 <= 4.
    msg = [0] * 24
    tally = encode(msg, T)
    tally[12] = 1
    tally[28] = ERASURE
    decoded, status = decode_erasures(tally, 24, T)
    assert status == "ok" and decoded == [int(i == 12) for i in range(24)]


def test_no_wrong_message_without_errors() -> None:
    # Con e = 0 la parola vera è sempre una soluzione: «ok» solo col messaggio giusto.
    rng = random.Random(5)
    for _ in range(300):
        msg = [rng.getrandbits(1) for _ in range(24)]
        tally = encode(msg, T)
        for i in rng.sample(range(32), rng.randint(0, 12)):
            tally[i] = ERASURE
        decoded, status = decode_erasures(tally, 24, T)
        assert status in ("ok", "ambiguous") and (decoded is None or decoded == msg)
