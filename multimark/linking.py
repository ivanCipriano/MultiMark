"""Legame sito → bit e maschera con la chiave (PIPELINE_metodo.md §3.4–3.5, §4.1, §4.2 punto 2).

- ``multimark`` (2A, ``linking=function_channel``)::

      off(f, c) = prf_int(K, "offset", name(f), str(n_params(f)), c) mod B
      phi(s)    = (off(f, c) + rank(s)) mod B

  Il canale dei nomi è il canale ``"names"``; con V1 (2 bit per variabile) la variabile di rango
  ``r`` occupa le posizioni ``off + 2r`` e ``off + 2r + 1``.
- ``function_single_run`` (ablazione): un solo ``off(f) = prf_int(K, "offset", name, n_params)``
  e un rango unico su tutti i siti della funzione, nell'ordine di §3.9 (canali 1..14, poi i nomi).
  TODO(ivan): la pipeline non dice se i nomi entrano nel rango unico; qui sì, dopo i canali.
- ``mcss`` (``positional``): pool «prima tutte le variabili (2 posizioni ciascuna), poi i siti
  strutturali», in ordine di visita; per il ciclo ``k = i // B`` una permutazione di ``0..B-1``
  con Fisher-Yates guidato dal flusso ``prf_int(K, "fy", str(j))``, ``j = 0, 1, …`` consumato in
  ordine (decisione I di §7: le permutazioni dei primi cicli non dipendono da ``N``);
  ``phi(i) = perm_k[i mod B]``. Fisher-Yates «moderno»: per ``i`` da ``B-1`` a ``1``,
  ``r = flusso mod (i+1)`` e scambio di ``perm[i]`` e ``perm[r]`` (lo scarto dovuto al modulo su
  64 bit è trascurabile).
- Maschera (1B): ``mask(s) = prf_bit(K, "mask", name(f), str(n_params(f)), c, str(rank(s)))``.
"""

from __future__ import annotations

from multimark.prf import prf_bit, prf_int

LINKING_MODES = ("function_channel", "function_single_run", "positional")


def offset(key: int, fid_name: str, n_params: int, channel: str, b: int) -> int:
    """``off(f, c)`` di §3.4."""
    return prf_int(key, "offset", fid_name, str(n_params), channel) % b


def phi_function(key: int, fid_name: str, n_params: int, channel: str, rank: int, b: int) -> int:
    """Indice del bit per un sito con ``linking=function_channel``."""
    return (offset(key, fid_name, n_params, channel, b) + rank) % b


def phi_single_run(key: int, fid_name: str, n_params: int, run_rank: int, b: int) -> int:
    """Indice del bit con ``linking=function_single_run`` (rango su tutti i canali della
    funzione)."""
    return (prf_int(key, "offset", fid_name, str(n_params)) + run_rank) % b


def permutations(key: int, n_cycles: int, b: int) -> list[list[int]]:
    """Le prime ``n_cycles`` permutazioni di ``0..b-1`` (Fisher-Yates sul flusso ``"fy"``)."""
    perms: list[list[int]] = []
    j = 0
    for _ in range(n_cycles):
        perm = list(range(b))
        for i in range(b - 1, 0, -1):
            r = prf_int(key, "fy", str(j)) % (i + 1)
            j += 1
            perm[i], perm[r] = perm[r], perm[i]
        perms.append(perm)
    return perms


def phi_positional(key: int, n_slots: int, b: int) -> list[int]:
    """Indici dei bit per le ``n_slots`` posizioni del pool di MCSS (§4.1)."""
    n_cycles = -(-n_slots // b) if n_slots else 0
    perms = permutations(key, n_cycles, b)
    return [perms[i // b][i % b] for i in range(n_slots)]


def mask(key: int, fid_name: str, n_params: int, channel: str, rank: int) -> int:
    """Bit di maschera di un sito strutturale (§3.5)."""
    return prf_bit(key, "mask", fid_name, str(n_params), channel, str(rank))
