"""Legame sito → bit e maschera con la chiave (PIPELINE_metodo.md §3.4–3.5, §4.1). Arriva in P1.

- ``multimark`` (2A, ``linking=function_channel``):
  ``off(f, c) = prf_int(K, "offset", name(f), str(n_params(f)), c) mod B``,
  ``phi(s) = (off(f, c) + rank(s)) mod B``.
- ``function_single_run``: un solo ``off(f)`` e rango su tutti i canali della funzione.
- ``mcss`` (``positional``): pool «prima le variabili poi i siti strutturali», permutazioni
  Fisher-Yates a cicli completi guidate da ``prf_int(K, "fy", str(j))``.
- Maschera (1B): ``mask(s) = prf_bit(K, "mask", name(f), str(n_params(f)), c, str(rank(s)))``.
"""

from __future__ import annotations

LINKING_MODES = ("function_channel", "function_single_run", "positional")


def phi_function(key: int, fid_name: str, n_params: int, channel: str, rank: int, b: int) -> int:
    """Indice del bit per un sito con ``linking=function_channel``."""
    raise NotImplementedError("P1: phi_function (§3.4)")


def phi_positional(key: int, n_slots: int, b: int) -> list[int]:
    """Indici dei bit per le ``n_slots`` posizioni del pool di MCSS (§4.1)."""
    raise NotImplementedError("P1: phi_positional (§4.1)")


def mask(key: int, fid_name: str, n_params: int, channel: str, rank: int) -> int:
    """Bit di maschera di un sito strutturale (§3.5)."""
    raise NotImplementedError("P1: maschera (§3.5)")
