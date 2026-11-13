"""PRF (§3.5), seme derivato (§3.10.1), alfabeto e codice compatto (§3.7–3.8)."""

from __future__ import annotations

import hashlib
import hmac
import random

import pytest

from multimark.codec import (
    ERASURE,
    bits_to_text,
    codeword_length,
    decode_erasures,
    encode,
    matrix_digest,
    parity_matrix,
    text_to_bits,
)
from multimark.prf import derive_seed, prf, prf_bit, prf_int


def test_prf_definition() -> None:
    expected = hmac.new((7).to_bytes(8, "big"), b"mask|f|2|aug_assign|0", hashlib.sha256).digest()
    assert prf(7, "mask", "f", "2", "aug_assign", "0") == expected
    assert prf_int(7, "a") == int.from_bytes(prf(7, "a")[:8], "big")
    assert prf_bit(7, "a") == prf(7, "a")[-1] & 1
    with pytest.raises(ValueError):
        prf(-1, "a")


def test_prf_bits_are_balanced() -> None:
    ones = sum(prf_bit(12345, "name", f"var_{i}") for i in range(2000))
    assert 900 < ones < 1100


def test_derive_seed_matches_benchmark_definition() -> None:
    payload = b"20261001|multimark-registry|1"
    expected = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**31 - 1)
    assert derive_seed(20261001, "multimark-registry", "1") == expected
    assert derive_seed(1, None) == derive_seed("1", "None")


def test_alphabet_roundtrip() -> None:
    bits = text_to_bits("gpt4")
    assert len(bits) == 24 and bits_to_text(bits) == "gpt4"
    assert text_to_bits("a") == [0] * 6 and text_to_bits("_") == [1, 1, 1, 1, 1, 0]
    assert bits_to_text(text_to_bits("ab", n_chars=4)) == "ab"
    with pytest.raises(ValueError):
        text_to_bits("a-b")
    with pytest.raises(ValueError):
        bits_to_text([0] * 5)


def test_matrix_is_fixed() -> None:
    # Valore di controllo della matrice (§3.8): cambia solo se cambia la costruzione.
    assert matrix_digest(24, 2) == MATRIX_24_2_SHA256
    p = parity_matrix(24, 2)
    assert len(p) == 24 and all(len(r) == 8 for r in p)
    assert parity_matrix(24, 0) == [[] for _ in range(24)]
    assert [codeword_length(24, t) for t in (0, 2, 4, 8)] == [24, 32, 40, 56]


MATRIX_24_2_SHA256 = "b671eb3e8cb7832152c5d08b794f10d5579d607babd016072a371b77065e259c"


def _msg(rng: random.Random, n: int = 24) -> list[int]:
    return [rng.getrandbits(1) for _ in range(n)]


@pytest.mark.parametrize("t", [0, 2, 4, 8])
def test_encode_is_systematic_and_linear(t: int) -> None:
    rng = random.Random(t)
    a, b = _msg(rng), _msg(rng)
    ca, cb = encode(a, t), encode(b, t)
    assert ca[:24] == a and len(ca) == 24 + 4 * t
    assert encode([x ^ y for x, y in zip(a, b)], t) == [x ^ y for x, y in zip(ca, cb)]


@pytest.mark.parametrize("t", [0, 2, 4, 8])
def test_decode_without_erasures(t: int) -> None:
    rng = random.Random(100 + t)
    for _ in range(50):
        m = _msg(rng)
        assert decode_erasures(encode(m, t), 24, t) == (m, "ok")


@pytest.mark.parametrize("t", [2, 4, 8])
def test_decode_recovers_erasures_when_unique(t: int) -> None:
    rng = random.Random(200 + t)
    recovered = 0
    for _ in range(200):
        m = _msg(rng)
        cw = encode(m, t)
        k = rng.randint(1, 4 * t)
        erased = rng.sample(range(len(cw)), k)
        tally = [ERASURE if i in erased else v for i, v in enumerate(cw)]
        decoded, status = decode_erasures(tally, 24, t)
        assert status in ("ok", "ambiguous")
        if status == "ok":
            assert decoded == m
            recovered += 1
    assert recovered > 0


def test_decode_parity_erasures_only_is_always_ok() -> None:
    m = _msg(random.Random(5))
    cw = encode(m, 2)
    tally = cw[:24] + [ERASURE] * 8
    assert decode_erasures(tally, 24, 2) == (m, "ok")


def test_decode_too_many_erasures_is_ambiguous() -> None:
    cw = encode(_msg(random.Random(6)), 2)
    tally = [ERASURE] * 9 + cw[9:]
    assert decode_erasures(tally, 24, 2)[1] == "ambiguous"
    assert decode_erasures([ERASURE] + cw[1:24], 24, 0) == (None, "ambiguous")


def test_decode_detects_inconsistency() -> None:
    rng = random.Random(7)
    seen = False
    for _ in range(50):
        cw = encode(_msg(rng), 2)
        flipped = list(cw)
        flipped[rng.randrange(24)] ^= 1  # errore (non cancellazione) su un bit del messaggio
        decoded, status = decode_erasures(flipped, 24, 2)
        if status == "inconsistent":
            seen = True
            assert decoded is None
    assert seen


def test_decode_input_validation() -> None:
    with pytest.raises(ValueError):
        decode_erasures([0] * 31, 24, 2)
    with pytest.raises(ValueError):
        decode_erasures([2] * 32, 24, 2)
    with pytest.raises(ValueError):
        encode([0, 2], 2)
