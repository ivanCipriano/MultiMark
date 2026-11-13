"""Rilevazione (PIPELINE_metodo.md §3.10).

Due modalità sugli stessi voti:

- **confronto con il registro** (1A): per ``N_reg ∈ {1, 16, 1024}`` il candidato del registro
  (messaggio atteso più ``N_reg - 1`` esche, §3.10.1) con la massima concordanza ``A`` e il
  punteggio ``-log10 P[Bin(N, 1/2) ≥ A]`` (esatto con ``math.comb``; con pesi non uniformi,
  approssimazione normale). Punteggio principale: ``N_reg = 1``.
- **decodifica aperta**: voto a maggioranza per bit (pareggio o nessun voto → cancellazione),
  decodifica per cancellazioni (§3.8), ``bits_correct`` sui bit del messaggio decisi
  (decisione L di §7: con decodifica ambigua o incoerente contano i bit decisi dal voto).

``native_decision`` (diagnostica, §3.10.2): ``multimark`` → ``P · N_reg ≤ 0,01`` con
``N_reg = 1``; ``mcss`` → decodifica riuscita e uguale al messaggio atteso (§4.2 punto 5).
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from multimark import __version__
from multimark._astindex import AstIndex
from multimark.channels import CHANNELS
from multimark.codec import ERASURE, decode_erasures, encode
from multimark.config import Config
from multimark.embed import message_to_bits
from multimark.layout import Vote, build_layout, read_votes
from multimark.prf import derive_seed

DETECT_STATUSES = ("OK", "FAILED")
REGISTRY_SIZES: tuple[int, ...] = (1, 16, 1024)

EXTRA_FIELDS: tuple[str, ...] = (
    "n_sites",
    "n_votes",
    "n_sites_by_channel",
    "n_name_sites",
    "agreement",
    "score_nreg16",
    "score_nreg1024",
    "score_decode",
    "best_nreg16",
    "best_nreg1024",
    "decoded_message_open",
    "decode_status",
    "bits_correct",
    "n_erasures",
    "sites",
    "skipped_sites",
    "library_version",
)


@dataclass
class DetectResult:
    """Esito della rilevazione: stato, punteggio principale, ``extra`` di §3.10.4."""

    status: str
    score: Optional[float] = None
    reason: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)
    decoded_message: Optional[str] = None
    native_decision: Optional[bool] = None


def bits_str(bits: Sequence[int]) -> str:
    return "".join(str(b) for b in bits)


def binom_tail_log10(n: int, a: int) -> float:
    """``log10 P[Bin(n, 1/2) ≥ a]`` esatto."""
    if a <= 0:
        return 0.0
    if a > n:
        return -math.inf
    tail = sum(math.comb(n, k) for k in range(a, n + 1))
    return math.log10(tail) - n * math.log10(2)


def binom_tail_score(n: int, a: int) -> float:
    """``-log10(P[Bin(N, 1/2) ≥ A])`` esatto con ``math.comb`` (§3.10.2)."""
    return -binom_tail_log10(n, a)


def normal_tail_score(agreement: float, total: float) -> float:
    """Pesi non uniformi: ``z = (2A − W)/√W``, ``score = -log10(Φ̄(z))`` (§3.10.2)."""
    if total <= 0:
        return 0.0
    z = (2 * agreement - total) / math.sqrt(total)
    tail = 0.5 * math.erfc(z / math.sqrt(2))
    return -math.log10(tail) if tail > 0 else math.inf


def registry_decoys(
    registry_seed: int, method: str, k: int, expected: Sequence[int], message_bits: int
) -> list[list[int]]:
    """``k`` esche (§3.10.1): ``derive_seed(seed, "<metodo>-registry", str(j)) % 2**bits`` per
    ``j = 1..k``; un'esca uguale al messaggio atteso si sostituisce con quella di ``j + 10**6``."""
    out: list[list[int]] = []
    exp = list(expected)
    for j in range(1, k + 1):
        value = derive_seed(registry_seed, f"{method}-registry", str(j)) % 2**message_bits
        bits = [int(c) for c in format(value, f"0{message_bits}b")]
        if bits == exp:
            value = (
                derive_seed(registry_seed, f"{method}-registry", str(j + 10**6)) % 2**message_bits
            )
            bits = [int(c) for c in format(value, f"0{message_bits}b")]
        out.append(bits)
    return out


def _load_weights(cfg: Config) -> Optional[dict[str, float]]:
    if cfg.voting == "simple":
        return None
    if cfg.voting == "weighted_erasure":
        # TODO(ivan): la pipeline nomina «voto pesato con cancellazioni» senza definirlo (P7.5).
        raise NotImplementedError("voting=weighted_erasure is not defined yet")
    assert cfg.channel_weights is not None
    data = json.loads(Path(cfg.channel_weights).read_text(encoding="utf-8"))
    return {str(k): float(v) for k, v in data.items()}


def _agreement(votes: list[Vote], cw: list[int]) -> float:
    return sum(v.weight for v in votes if cw[v.index] == v.value)


def detect(
    code: str,
    expected: Union[str, Sequence[int]],
    key: int,
    cfg: Config,
    registry_sizes: Sequence[int] = REGISTRY_SIZES,
    registry_seed: Optional[int] = None,
    method: str = "multimark",
) -> DetectResult:
    """Rileva il watermark in ``code`` rispetto al messaggio atteso ``expected``."""
    exp = message_to_bits(expected, cfg.message_bits)
    try:
        index = AstIndex.from_code(code)
    except (SyntaxError, ValueError):
        return DetectResult("FAILED", reason="syntax_error", extra={"library_version": __version__})
    layout = build_layout(index, cfg, key)
    weights = _load_weights(cfg)
    votes = read_votes(layout, key, cfg, weights)
    by_channel = {c: 0 for c in CHANNELS}
    by_channel["names"] = 0
    for slot in layout.slots:
        by_channel[slot.channel] += 1
    extra: dict[str, Any] = {
        "n_sites": layout.n_bits,
        "n_votes": len(votes),
        "n_sites_by_channel": by_channel,
        "n_name_sites": len(layout.names),
        "skipped_sites": None,  # noto solo all'inserimento
        "library_version": __version__,
    }
    extra["sites"] = _site_records(layout, votes)
    if not votes:
        extra.update({f: None for f in EXTRA_FIELDS if f not in extra})
        return DetectResult("FAILED", reason="no_sites", extra=extra)

    seed = registry_seed if registry_seed is not None else cfg.registry_seed
    n = len(votes)
    total_w = sum(v.weight for v in votes)
    uniform = weights is None

    def score_of(cw: list[int]) -> tuple[float, float]:
        a = _agreement(votes, cw)
        s = binom_tail_score(n, int(round(a))) if uniform else normal_tail_score(a, total_w)
        return a, s

    a1, score1 = score_of(encode(exp, cfg.t))
    extra["agreement"] = a1
    for size in registry_sizes:
        if size == 1:
            continue
        if seed is None:
            raise ValueError("registry_seed is required for registry sizes > 1")
        cands = [exp, *registry_decoys(seed, method, size - 1, exp, cfg.message_bits)]
        scored = [(score_of(encode(m, cfg.t)), i) for i, m in enumerate(cands)]
        (a_best, s_best), i_best = max(scored, key=lambda x: (x[0][0], -x[1]))
        extra[f"score_nreg{size}"] = s_best
        extra[f"best_nreg{size}"] = bits_str(cands[i_best])
    for size in (16, 1024):
        extra.setdefault(f"score_nreg{size}", None)
        extra.setdefault(f"best_nreg{size}", None)

    # decodifica aperta
    tally = _majority(votes, layout.b)
    decoded, status = decode_erasures(tally, cfg.message_bits, cfg.t)
    if decoded is not None:
        bits_correct = sum(1 for d, e in zip(decoded, exp) if d == e)
    else:
        bits_correct = sum(
            1 for i in range(cfg.message_bits) if tally[i] != ERASURE and tally[i] == exp[i]
        )
    extra.update(
        decoded_message_open=bits_str(decoded) if decoded is not None else None,
        decode_status=status,
        bits_correct=bits_correct,
        n_erasures=sum(1 for v in tally if v == ERASURE),
        score_decode=bits_correct / cfg.message_bits,
    )
    native: Optional[bool]
    if method == "mcss":
        native = decoded is not None and decoded == exp
    else:
        native = binom_tail_log10(n, int(round(a1))) <= math.log10(0.01) if uniform else None
    extra["native_decision"] = native
    return DetectResult(
        "OK",
        score=score1,
        extra=extra,
        decoded_message=extra["decoded_message_open"],
        native_decision=native,
    )


def _majority(votes: list[Vote], b: int) -> list[int]:
    ones = [0.0] * b
    zeros = [0.0] * b
    for v in votes:
        if v.value:
            ones[v.index] += v.weight
        else:
            zeros[v.index] += v.weight
    return [1 if o > z else 0 if z > o else ERASURE for o, z in zip(ones, zeros)]


def _site_records(layout: Any, votes: list[Vote]) -> list[list[Any]]:
    """``[fid_name, n_params, channel, rank, value_read, vote]`` per voto (§3.10.4); i siti dei
    nomi non leggibili compaiono con ``value_read`` e ``vote`` ``null``. Con V1 una variabile
    porta due voti: il secondo ha canale ``names_b1``."""
    by_slot: dict[int, list[Vote]] = {}
    for v in votes:
        by_slot.setdefault(id(v.slot), []).append(v)
    out: list[list[Any]] = []
    for slot in layout.slots:
        unit = slot.site.unit if slot.site is not None else slot.name.unit
        rank = slot.site.rank if slot.site is not None else slot.name.rank
        vs = by_slot.get(id(slot), [])
        if not vs:
            out.append([unit.name, unit.n_params, slot.channel, rank, None, None])
        for j, v in enumerate(vs):
            channel = slot.channel if j == 0 else f"{slot.channel}_b1"
            out.append([unit.name, unit.n_params, channel, rank, v.value_read, v.value])
    return out


__all__ = ["DetectResult", "binom_tail_score", "detect", "registry_decoys"]
