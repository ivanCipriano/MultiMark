"""Messaggio, alfabeto a 6 bit e codice compatto (PIPELINE_metodo.md §3.7–3.8). Arriva in P1.

- Alfabeto di MCSS (p. 4–5): a–z 0–25, A–Z 26–51, 0–9 52–61, ``_`` 62, riempimento 63.
- Codice sistematico lineare su GF(2): ``cw = m ∥ m·P``, ``P`` matrice ``message_bits × 4t`` dal
  seme ``sha256(b"posthoc-compact-code-v1")``; ``B = message_bits + 4t``.
- Decodifica per sole cancellazioni (Teorema 5.2 di MCSS, p. 7) con eliminazione di Gauss.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

#: Valore del voto per bit senza decisione (pareggio o nessun voto).
ERASURE = -1

DECODE_STATUSES = ("ok", "inconsistent", "ambiguous")


def codeword_length(message_bits: int, t: int) -> int:
    """``B = message_bits + 4t``."""
    return message_bits + 4 * t


def text_to_bits(text: str) -> list[int]:
    """Testo → bit con l'alfabeto a 6 bit (solo per il dimostratore)."""
    raise NotImplementedError("P1: alfabeto a 6 bit (§3.7)")


def bits_to_text(bits: Sequence[int]) -> str:
    """Bit → testo con l'alfabeto a 6 bit."""
    raise NotImplementedError("P1: alfabeto a 6 bit (§3.7)")


def parity_matrix(message_bits: int, t: int) -> list[list[int]]:
    """Matrice ``P`` (``message_bits × 4t``) del codice compatto."""
    raise NotImplementedError("P1: matrice del codice compatto (§3.8)")


def encode(message: Sequence[int], t: int) -> list[int]:
    """Parola di codice ``cw = m ∥ m·P`` di lunghezza ``B``."""
    raise NotImplementedError("P1: codifica (§3.8)")


def decode_erasures(
    tally: Sequence[int], message_bits: int, t: int
) -> tuple[Optional[list[int]], str]:
    """Decodifica per cancellazioni: ``(messaggio o None, decode_status)``."""
    raise NotImplementedError("P1: decodifica per cancellazioni (§3.8)")
