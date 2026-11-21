"""Proponente neurale dei nomi (PIPELINE_metodo.md §3.6.4, §P3 punto 1; MD31).

``NeuralProposer`` chiede a un modello chat (base ``Qwen/Qwen2.5-Coder-0.5B-Instruct``) un elenco di
nomi alternativi per una variabile. Regole:

- prompt di §3.6.4: messaggio di sistema con il numero di nomi richiesti (``N_CANDIDATES = 16``,
  scelta di Ivan del 21 novembre per ``names.bits_per_name = 2``) e messaggio utente con il codice
  della funzione, la variabile evidenziata come ``<<var_name>>`` e la riga
  ``Variable to rename: var_name``;
- decodifica greedy, ``MAX_NEW_TOKENS`` token nuovi; si tengono solo gli identificatori validi
  (§3.6.4, ``names.valid_new_name`` rispetto ai nomi della funzione), nell'ordine del modello;
- il codice del prompt è quello **normalizzato** (``ast.unparse``: niente commenti né spaziature),
  e la cache è per (codice normalizzato, funzione, variabile): a parità di codice letto i candidati
  sono gli stessi, chiamata dopo chiamata e worker dopo worker;
- il modello si carica una volta sola, alla prima richiesta (``shared_proposer`` per il worker);
- il ripiego su ``StaticProposer`` lo fa l'inserimento (``embed._choose_name``): se nessun
  candidato neurale ha i bit giusti, per quel nome si usano i candidati statici, e il registro conta
  il nome in ``n_names_neural_fallback``.

La lettura non usa il modello: il bit viene dal nome (``names.name_bits``). ``torch`` e
``transformers`` servono solo per ``HFGenerator`` (extra ``[neural]``) e si importano lì.
"""

from __future__ import annotations

import ast
import json
import re
from collections import OrderedDict
from collections.abc import Sequence
from functools import lru_cache
from typing import Callable, Optional

from multimark._astindex import FUNCTION_TYPES, AstIndex, iter_preorder
from multimark.names import _scope_identifiers_of, name_sites, valid_new_name

DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
#: Nomi chiesti al modello per variabile (§3.6.4 ne dice 8; 16 per ``bits_per_name = 2``, MD31).
N_CANDIDATES = 16
#: §3.6.4 fissa 64 token per 8 nomi; con 16 nomi il budget raddoppia (MD31).
MAX_NEW_TOKENS = 128
SYSTEM_PROMPT = (
    "You rename one variable in Python code. Answer with a JSON list of {k} alternative "
    "snake_case names, most natural first, no explanations."
)
CACHE_SIZE = 200_000
#: prompt per chiamata al modello (un codice con più variabili si divide in lotti consecutivi)
BATCH_SIZE = 32

#: Messaggi chat ``[{"role": ..., "content": ...}, ...]`` → testo generato.
Messages = list[dict[str, str]]
Generator = Callable[[Sequence[Messages]], list[str]]

_QUOTED = re.compile(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']")


def normalize_code(code: str) -> str:
    """Codice normalizzato della chiave di cache e del prompt: ``ast.unparse`` del modulo."""
    return ast.unparse(ast.parse(code))


def _function_node(tree: ast.Module, function_name: str, var_name: str) -> Optional[ast.AST]:
    """La prima funzione ``function_name`` che usa ``var_name`` (altrimenti la prima con quel nome);
    ``None`` per le variabili di modulo (``function_name == ""``) o se non si trova."""
    if not function_name:
        return None
    first = None
    for node in iter_preorder(tree):
        if isinstance(node, FUNCTION_TYPES) and node.name == function_name:
            first = first or node
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Name) and sub.id == var_name) or (
                    isinstance(sub, ast.arg) and sub.arg == var_name
                ):
                    return node
    return first


def _binds_locally(fn: ast.AST, var_name: str) -> bool:
    """La funzione (o lambda) ha un parametro o un binding ``var_name`` senza ``global``."""
    args = fn.args  # type: ignore[attr-defined]
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    if any(a is not None and a.arg == var_name for a in params):
        return True
    body = fn.body if isinstance(fn.body, list) else [fn.body]  # type: ignore[attr-defined]
    stores = declared = False
    for stmt in body:
        for sub in ast.walk(stmt):
            if isinstance(sub, (ast.Global, ast.Nonlocal)) and var_name in sub.names:
                declared = True
            elif (
                isinstance(sub, ast.Name)
                and sub.id == var_name
                and not isinstance(sub.ctx, ast.Load)
            ):
                stores = True
    return stores and not declared


def _occurrences(scope: ast.AST, var_name: str, module: bool) -> list[ast.AST]:
    """``Name`` e parametri ``var_name`` in ``scope``; per una variabile di modulo si saltano le
    funzioni che hanno un loro ``var_name`` locale (sono altre variabili)."""
    out: list[ast.AST] = []
    stack = [scope]
    while stack:
        node = stack.pop()
        if (
            module
            and isinstance(node, (*FUNCTION_TYPES, ast.Lambda))
            and _binds_locally(node, var_name)
        ):
            continue
        if (isinstance(node, ast.Name) and node.id == var_name) or (
            isinstance(node, ast.arg) and node.arg == var_name
        ):
            out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def highlighted_source(normalized: str, function_name: str, var_name: str) -> str:
    """Sorgente della funzione (o del modulo, per una variabile di modulo) dal codice normalizzato,
    con ogni occorrenza della variabile (``Name`` e parametri) scritta ``<<var_name>>``."""
    tree = ast.parse(normalized)
    node = _function_node(tree, function_name, var_name)
    lines = normalized.split("\n")
    scope: ast.AST = tree
    first, last = 1, len(lines)
    if isinstance(node, FUNCTION_TYPES):
        scope = node
        first, last = node.lineno, node.end_lineno or node.lineno
        if node.decorator_list:
            first = min(first, *(d.lineno for d in node.decorator_list))
    spots: dict[int, list[int]] = {}
    for sub in _occurrences(scope, var_name, module=node is None):
        assert isinstance(sub, (ast.Name, ast.arg))
        spots.setdefault(sub.lineno, []).append(sub.col_offset)
    for lineno, cols in spots.items():
        raw = lines[lineno - 1].encode("utf-8")
        width = len(var_name.encode("utf-8"))
        for col in sorted(cols, reverse=True):  # offset in byte UTF-8 (ast)
            raw = raw[:col] + b"<<" + raw[col : col + width] + b">>" + raw[col + width :]
        lines[lineno - 1] = raw.decode("utf-8")
    return "\n".join(lines[first - 1 : last])


def build_messages(normalized: str, function_name: str, var_name: str, k: int) -> Messages:
    """Prompt chat di §3.6.4 per una variabile."""
    source = highlighted_source(normalized, function_name, var_name)
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(k=k)},
        {"role": "user", "content": f"{source}\n\nVariable to rename: {var_name}"},
    ]


def parse_names(text: str) -> list[str]:
    """Nomi dalla risposta del modello: la lista JSON se si legge; altrimenti (per esempio troncata
    da ``MAX_NEW_TOKENS``) le stringhe fra virgolette che sono identificatori, nell'ordine."""
    start = text.find("[")
    if start >= 0:
        end = text.find("]", start)
        if end > start:
            try:
                data = json.loads(text[start : end + 1])
            except ValueError:
                data = None
            if isinstance(data, list):
                return [x for x in data if isinstance(x, str)]
    return _QUOTED.findall(text)


def batch_variables(normalized: str) -> list[tuple[str, str]]:
    """(funzione, variabile) di tutti i siti dei nomi possibili nel codice, con le opzioni più
    larghe (parametri, variabili di modulo, nomi di una lettera): un insieme che comprende i siti di
    ogni configurazione, ordinato."""
    index = AstIndex.from_code(normalized)
    sites = name_sites(index, include_params=True, module_level=True, single_letter="extend_all")
    return sorted({(s.unit.name, s.name) for s in sites})


class NeuralProposer:
    """Proponente neurale (§3.6.4). ``generate`` riceve un lotto di prompt chat e restituisce un
    testo per prompt; di default ``HFGenerator(model)``, creato alla prima richiesta."""

    #: dimensione dell'elenco neurale; l'inserimento lo usa al posto dei passi 8 → 32 statici
    n_candidates = N_CANDIDATES

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        generate: Optional[Generator] = None,
        n_candidates: int = N_CANDIDATES,
    ) -> None:
        self.model = model
        self.n_candidates = n_candidates
        self._generate = generate
        self._cache: OrderedDict[tuple[str, str, str], tuple[str, ...]] = OrderedDict()
        #: numero di prompt mandati al modello (le risposte in cache non contano)
        self.n_generated = 0

    @property
    def generator(self) -> Generator:
        if self._generate is None:
            self._generate = HFGenerator(self.model)
        return self._generate

    def _raw(self, code: str, function_name: str, var_name: str) -> tuple[str, ...]:
        normalized = normalize_code(code)
        key = (normalized, function_name, var_name)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        # Un lotto per codice: tutte le variabili del codice normalizzato (``batch_variables``), in
        # ordine fisso. Il lotto dipende solo dal codice, quindi anche la risposta del modello a
        # ogni prompt (riempimento compreso) dipende solo dal codice, non da chiave, messaggio o
        # configurazione.
        wanted = batch_variables(normalized)
        if (function_name, var_name) not in wanted:
            wanted = [(function_name, var_name)]  # fuori dall'insieme: prompt da solo
        prompts = [build_messages(normalized, f, v, self.n_candidates) for f, v in wanted]
        texts: list[str] = []
        for i in range(0, len(prompts), BATCH_SIZE):
            texts += self.generator(prompts[i : i + BATCH_SIZE])
        self.n_generated += len(prompts)
        out: tuple[str, ...] = ()
        for (f, v), text in zip(wanted, texts):
            names = tuple(parse_names(text))
            self._cache[(normalized, f, v)] = names
            if (f, v) == (function_name, var_name):
                out = names
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return out

    def propose(self, code: str, function_name: str, var_name: str, k: int = 8) -> list[str]:
        """I primi ``k`` nomi validi (§3.6.4) proposti dal modello, senza duplicati; il controllo
        completo di scope lo rifà l'inserimento, come per ``StaticProposer``."""
        used = set(_scope_identifiers_of(code, function_name))
        out: list[str] = []
        for cand in self._raw(code, function_name, var_name):
            if cand not in out and valid_new_name(cand, var_name, used):
                out.append(cand)
            if len(out) == k:
                break
        return out


class HFGenerator:
    """Generazione greedy con ``transformers`` (extra ``[neural]``), un lotto di prompt per chiamata
    con riempimento a sinistra. A parità di lotto e di macchina la risposta è la stessa; il lotto lo
    fissa ``NeuralProposer`` dal solo codice."""

    def __init__(self, model: str, device: Optional[str] = None, dtype: str = "float32") -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        self.model = AutoModelForCausalLM.from_pretrained(model, dtype=getattr(torch, dtype))
        self.model.to(self.device).eval()
        self.tokenizer.padding_side = "left"
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

    def __call__(self, batch: Sequence[Messages]) -> list[str]:
        if not batch:
            return []
        texts = [
            self.tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
            for m in batch
        ]
        enc = self.tokenizer(texts, return_tensors="pt", padding=True).to(self.device)
        with self.torch.inference_mode():
            gen = self.model.generate(
                **enc,
                do_sample=False,
                temperature=None,
                top_p=None,
                top_k=None,
                max_new_tokens=MAX_NEW_TOKENS,
                pad_token_id=self.tokenizer.pad_token_id,
            )
        new = gen[:, enc["input_ids"].shape[1] :]
        return self.tokenizer.batch_decode(new, skip_special_tokens=True)


@lru_cache(maxsize=4)
def shared_proposer(model: str = DEFAULT_MODEL) -> NeuralProposer:
    """Un ``NeuralProposer`` per modello e per processo (worker): modello e cache si condividono fra
    tutte le chiamate di ``embed`` del worker."""
    return NeuralProposer(model)
