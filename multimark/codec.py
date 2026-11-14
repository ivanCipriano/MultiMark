"""Messaggio, alfabeto a 6 bit e codice compatto (PIPELINE_metodo.md §3.7–3.8).

- Alfabeto di MCSS (p. 4–5): a–z 0–25, A–Z 26–51, 0–9 52–61, ``_`` 62, riempimento 63.
- Codice sistematico lineare su GF(2): ``cw = m ∥ m·P``, ``P`` matrice ``message_bits × 4t`` a
  elementi casuali da ``random.Random(int.from_bytes(sha256(b"posthoc-compact-code-v1")[:8]))``,
  letti riga per riga; ``B = message_bits + 4t``. La matrice del paper non è nota (seme non
  pubblicato, p. 3): la nostra ha la stessa costruzione e un seme nostro (MD7).
- **[v1.2.2] Matrice per profilo** (``code.matrix``, MD18): ``random`` è la costruzione sopra
  (``mcss``); ``dmin4`` ha come righe ``message_bits`` vettori distinti di ``4t`` bit di peso
  dispari ≥ 3, estratti con ``random.Random(seme).sample`` dalla lista ordinata di tutti questi
  vettori (seme dai primi 8 byte di ``sha256(b"multimark-compact-code-dmin4-v1")``). Ogni parola
  di codice non nulla ha allora peso pari e ≥ 4: distanza minima 4 (codice di Hamming esteso
  accorciato). Lista ordinata: per valore intero, con il primo bit della riga come bit più
  significativo (ordine lessicografico delle tuple di bit).
- Decodifica per sole cancellazioni (Teorema 5.2 di MCSS, p. 7): i bit decisi dal voto sono noti;
  per le posizioni cancellate si risolve ``H · cw = 0`` (``H = [Pᵀ | I]``) con eliminazione di Gauss
  su GF(2). Soluzione unica → messaggio; nessuna → ``inconsistent``; più di una → ``ambiguous``.
  Nessuna correzione di errori.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from functools import cache
from typing import Optional

#: Valore del voto per bit senza decisione (pareggio o nessun voto).
ERASURE = -1

DECODE_STATUSES = ("ok", "inconsistent", "ambiguous")

ALPHABET = (
    "abcdefghijklmnopqrstuvwxyz" "ABCDEFGHIJKLMNOPQRSTUVWXYZ" "0123456789" "_"
)  # fmt: skip
PAD = 63
_SEED_LABEL = b"posthoc-compact-code-v1"
_DMIN4_SEED_LABEL = b"multimark-compact-code-dmin4-v1"
#: Valori di ``code.matrix`` (§3.11 [v1.2.2]).
MATRICES = ("random", "dmin4")
#: Oltre questa lunghezza la lista ordinata di ``dmin4`` non si enumera (t = 8: ~2^31 vettori).
_DMIN4_MAX_PARITY = 16


def codeword_length(message_bits: int, t: int) -> int:
    """``B = message_bits + 4t``."""
    return message_bits + 4 * t


def text_to_bits(text: str, n_chars: Optional[int] = None) -> list[int]:
    """Testo → bit (6 per carattere, il più significativo prima); con ``n_chars`` si completa con
    il simbolo di riempimento 63. Solo per il dimostratore: il benchmark lavora in bit."""
    if n_chars is not None:
        if len(text) > n_chars:
            raise ValueError(f"text longer than {n_chars} characters")
    bits: list[int] = []
    codes = [ALPHABET.index(c) if c in ALPHABET else _bad_char(c) for c in text]
    if n_chars is not None:
        codes += [PAD] * (n_chars - len(text))
    for code in codes:
        bits.extend((code >> (5 - i)) & 1 for i in range(6))
    return bits


def _bad_char(c: str) -> int:
    raise ValueError(f"character {c!r} not in the 6-bit alphabet")


def bits_to_text(bits: Sequence[int]) -> str:
    """Bit → testo; il simbolo di riempimento si toglie."""
    if len(bits) % 6:
        raise ValueError("bit length must be a multiple of 6")
    out = []
    for i in range(0, len(bits), 6):
        code = 0
        for b in bits[i : i + 6]:
            code = (code << 1) | (b & 1)
        if code != PAD:
            out.append(ALPHABET[code])
    return "".join(out)


def _seed(label: bytes) -> int:
    return int.from_bytes(hashlib.sha256(label).digest()[:8], "big")


def dmin4_candidates(n_parity: int) -> list[tuple[int, ...]]:
    """Lista ordinata dei vettori di ``n_parity`` bit di peso dispari ≥ 3 (120 per 8 bit)."""
    if n_parity > _DMIN4_MAX_PARITY:
        # TODO(ivan): §3.8 definisce dmin4 per t = 2; per t = 8 la lista (~2^31) non si enumera.
        raise NotImplementedError(f"code.matrix=dmin4 is not defined for {n_parity} parity bits")
    out = []
    for value in range(2**n_parity):
        vec = tuple((value >> (n_parity - 1 - i)) & 1 for i in range(n_parity))
        weight = sum(vec)
        if weight >= 3 and weight % 2 == 1:
            out.append(vec)
    return out


@cache
def _matrix(
    message_bits: int, n_parity: int, matrix: str = "random"
) -> tuple[tuple[int, ...], ...]:
    if matrix not in MATRICES:
        raise ValueError(f"code.matrix must be one of {MATRICES}: {matrix!r}")
    if matrix == "dmin4" and n_parity > 0:
        pool = dmin4_candidates(n_parity)
        if len(pool) < message_bits:
            raise ValueError(f"dmin4 needs {message_bits} rows, only {len(pool)} vectors")
        return tuple(random.Random(_seed(_DMIN4_SEED_LABEL)).sample(pool, message_bits))
    rng = random.Random(_seed(_SEED_LABEL))
    return tuple(tuple(rng.getrandbits(1) for _ in range(n_parity)) for _ in range(message_bits))


def parity_matrix(message_bits: int, t: int, matrix: str = "random") -> list[list[int]]:
    """Matrice ``P`` (``message_bits × 4t``) del codice compatto."""
    return [list(row) for row in _matrix(message_bits, 4 * t, matrix)]


def matrix_digest(message_bits: int, t: int, matrix: str = "random") -> str:
    """SHA-256 della matrice (righe di ``0``/``1`` unite da ``\\n``): valore di controllo."""
    text = "\n".join("".join(map(str, row)) for row in _matrix(message_bits, 4 * t, matrix))
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _check_bits(bits: Sequence[int], name: str) -> None:
    if any(b not in (0, 1) for b in bits):
        raise ValueError(f"{name} must contain only 0/1")


def encode(message: Sequence[int], t: int, matrix: str = "random") -> list[int]:
    """Parola di codice ``cw = m ∥ m·P`` di lunghezza ``B``."""
    _check_bits(message, "message")
    rows = _matrix(len(message), 4 * t, matrix)
    parity = [0] * (4 * t)
    for bit, row in zip(message, rows):
        if bit:
            parity = [p ^ r for p, r in zip(parity, row)]
    return [*message, *parity]


def decode_erasures(
    tally: Sequence[int], message_bits: int, t: int, matrix: str = "random"
) -> tuple[Optional[list[int]], str]:
    """Decodifica per cancellazioni.

    ``tally``: ``B`` valori ``0``, ``1`` o ``ERASURE``. Restituisce ``(messaggio, "ok")`` se la
    soluzione è unica, ``(None, "inconsistent")`` se i bit noti violano le parità, ``(None,
    "ambiguous")`` se le cancellazioni lasciano più soluzioni."""
    b = codeword_length(message_bits, t)
    if len(tally) != b:
        raise ValueError(f"tally must have {b} entries")
    if any(v not in (0, 1, ERASURE) for v in tally):
        raise ValueError("tally entries must be 0, 1 or ERASURE")
    rows = _matrix(message_bits, 4 * t, matrix)
    unknown = [i for i, v in enumerate(tally) if v == ERASURE]
    col = {pos: k for k, pos in enumerate(unknown)}
    # Equazioni: per ogni parità j, sum_i P[i][j]·cw[i] + cw[message_bits + j] = 0.
    # Come bitmask sulle incognite, con termine noto.
    equations: list[tuple[int, int]] = []
    for j in range(4 * t):
        mask, rhs = 0, 0
        positions = [i for i in range(message_bits) if rows[i][j]] + [message_bits + j]
        for pos in positions:
            if pos in col:
                mask |= 1 << col[pos]
            else:
                rhs ^= tally[pos]
        equations.append((mask, rhs))
    # Eliminazione di Gauss su GF(2).
    pivots: dict[int, tuple[int, int]] = {}
    for mask, rhs in equations:
        for bit, (pmask, prhs) in pivots.items():
            if mask >> bit & 1:
                mask ^= pmask
                rhs ^= prhs
        if mask == 0:
            if rhs:
                return None, "inconsistent"
            continue
        lead = mask.bit_length() - 1
        for bit in list(pivots):
            pmask, prhs = pivots[bit]
            if pmask >> lead & 1:
                pivots[bit] = (pmask ^ mask, prhs ^ rhs)
        pivots[lead] = (mask, rhs)
    if len(pivots) < len(unknown):
        return None, "ambiguous"
    cw = list(tally)
    for lead, (mask, rhs) in pivots.items():
        assert mask == 1 << lead
        cw[unknown[lead]] = rhs
    return cw[:message_bits], "ok"
