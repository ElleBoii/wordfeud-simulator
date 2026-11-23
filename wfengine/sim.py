"""Monte Carlo-simulering (referensimplementation i ren Python, fas 4).

Flöde (SPEC 6.4):
 1. select_candidates: alla mina drag, de K bästa efter statisk värdering
    (poäng + leave) plus de bästa bytena och pass.
 2. För iteration i slumpas motståndarens hand och påsens ordning ur de osedda
    brickorna med en RNG som bara beror på (seed, i). Alla kandidater i samma
    iteration får alltså samma dragning (common random numbers).
 3. rollout: kandidaten spelas, sedan 'plies' drag framåt. Motståndaren väljer
    enligt sin modell (perfekt/mänsklig), jag med statisk värdering. Nya
    brickor dras ur påsen.
 4. Slutställningen görs om till vinstchans med vinstmodellen (eller exakt
    1/0,5/0 om matchen tog slut), och marginalen inkl. leave-värden sparas.
 5. CandidateStats håller medel och standardfel. Kandidater som parvis (över
    samma iterationer) är klart sämre än den bästa gallras bort.

rollout() är en ren funktion av (kontext, kandidat, iteration) och kan därför
köras i valfri process och ordning med samma resultat.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field

from .board import Board, Placement
from .dictionary import Dictionary
from .evaluation import LeaveModel, WinModel
from .fastgen import scored_plays
from .movegen import Move, generate_exchanges
from .rules import BLANK, Rules, final_adjustments, update_pass_count

ME, OPP = 0, 1
PERFECT, HUMAN = "perfect", "human"
# plies = 0 betyder "till slutet". Taket skyddar mot rollouts som aldrig tar slut
# (t.ex. ett låst bräde där båda bara byter); når man det används vinstmodellen.
END_PLIES = 100


# --- kontext -------------------------------------------------------------------

@dataclass
class SimContext:
    """Allt en rollout behöver (utom ordlistan). Går att pickla till arbetsprocesser."""
    rules: Rules
    layout: tuple[str, ...]
    tiles: tuple[tuple[int, int, str, bool], ...]   # brickor på brädet
    rack: str                                       # min hand
    unseen: tuple[str, ...]                         # osedda brickor (sorterade)
    scores: tuple[int, int]                         # (jag, motståndare)
    passes: int                                     # pass i rad före mitt drag
    leave_cfg: dict
    win_cfg: dict
    opponent_model: str = PERFECT
    human_top_n: int = 10
    human_temperature: float = 8.0
    plies: int = 2                                  # 0 = till slutet
    seed: int = 1

    def board(self) -> Board:
        b = Board(self.rules, self.layout)
        b.apply(Placement(*t) for t in self.tiles)
        return b


def iteration_rng(seed: int, iteration: int) -> random.Random:
    return random.Random((seed & 0xFFFFFFFF) * 1_000_003 + iteration)


def deal(ctx: SimContext, iteration: int) -> tuple[str, list[str]]:
    """Motståndarens hand och påsen (i dragordning) för en iteration."""
    tiles = list(ctx.unseen)
    iteration_rng(ctx.seed, iteration).shuffle(tiles)
    k = min(ctx.rules.rack_size, len(tiles))
    return "".join(tiles[:k]), tiles[k:]


# --- policy --------------------------------------------------------------------

def _remove(rack: str, used: str) -> str:
    left = list(rack)
    for ch in used:
        left.remove(ch)
    return "".join(left)


@dataclass
class Choice:
    kind: str                 # play / exchange / pass
    score: int = 0
    placements: tuple = ()    # ((r, c, letter, blank), ...)
    used: str = ""            # brickor från handen (blank = '?')
    value: float = 0.0


def ranked_plays(board: Board, rack: str, bag_len: int, dictionary: Dictionary,
                 leave: LeaveModel) -> list[Choice]:
    """Alla läggningar med statiskt värde (poäng + leave), osorterade."""
    out = []
    memo: dict[str, float] = {}
    bag_empty = bag_len == 0          # då kan inget fyllas på
    for score, pl in scored_plays(board, rack, dictionary):
        used = "".join(sorted(BLANK if b else ch for _, _, ch, b in pl))
        lv = memo.get(used)
        if lv is None:
            lv = leave.value(_remove(rack, used), bag_empty=bag_empty)
            memo[used] = lv
        out.append(Choice("play", score, pl, used, score + lv))
    return out


def best_exchange(rack: str, bag_len: int, rules: Rules, leave: LeaveModel) -> Choice | None:
    if not rack or bag_len < rules.exchange_min_bag:
        return None
    best = None
    for m in generate_exchanges(rack):
        v = leave.value(m.leave)
        if best is None or v > best.value:
            best = Choice("exchange", 0, (), m.exchanged, v)
    return best


def choose(board: Board, rack: str, bag_len: int, dictionary: Dictionary, leave: LeaveModel,
           rules: Rules, model: str = PERFECT, rng: random.Random | None = None,
           top_n: int = 10, temperature: float = 8.0) -> Choice:
    plays = ranked_plays(board, rack, bag_len, dictionary, leave)
    ex = best_exchange(rack, bag_len, rules, leave)
    options = plays + ([ex] if ex else [])
    if not options:
        return Choice("pass", value=leave.value(rack, bag_empty=bag_len == 0))
    if model == HUMAN and rng is not None and len(options) > 1:
        top = sorted(options, key=lambda c: -c.value)[:max(1, top_n)]
        t = max(1e-6, temperature)
        hi = top[0].value
        weights = [math.exp((c.value - hi) / t) for c in top]
        return rng.choices(top, weights)[0]
    return max(options, key=lambda c: c.value)


# --- rollout -------------------------------------------------------------------

@dataclass
class State:
    board: Board
    racks: list[str]
    bag: list[str]
    scores: list[int]
    passes: int
    to_move: int
    over: bool = False


def apply_choice(st: State, ch: Choice, rules: Rules, rng: random.Random) -> None:
    p = st.to_move
    rack = st.racks[p]
    if ch.kind == "play":
        st.board.apply(Placement(*t) for t in ch.placements)
        st.scores[p] += ch.score
        rack = _remove(rack, ch.used)
        k = min(len(ch.used), len(st.bag))
        rack += "".join(st.bag[:k])
        del st.bag[:k]
    elif ch.kind == "exchange":
        rack = _remove(rack, ch.used)
        k = len(ch.used)
        rack += "".join(st.bag[:k])
        del st.bag[:k]
        st.bag.extend(ch.used)
        rng.shuffle(st.bag)
    st.racks[p] = rack
    st.passes = update_pass_count(rules, st.passes, ch.kind)
    if st.passes >= rules.end_of_game["consecutive_passes_to_end"] or (not rack and not st.bag):
        st.over = True
        for i, a in enumerate(final_adjustments(rules, st.racks)):
            st.scores[i] += a
    st.to_move = 1 - p


def candidate_choice(m: Move) -> Choice:
    if m.kind == "play":
        pl = tuple((p.row, p.col, p.letter, p.blank) for p in m.placements)
        used = "".join(sorted(BLANK if p.blank else p.letter for p in m.placements))
        return Choice("play", m.score, pl, used)
    if m.kind == "exchange":
        return Choice("exchange", used=m.exchanged)
    return Choice("pass")


def rollout(ctx: SimContext, cand: Move, iteration: int, dictionary: Dictionary,
            leave: LeaveModel, win: WinModel, board: Board | None = None) -> tuple[float, float]:
    """Spelar kandidaten + ctx.plies drag. Ger (vinstchans 0–1, marginal)."""
    rules = ctx.rules
    opp_rack, bag = deal(ctx, iteration)
    st = State(board.copy() if board is not None else ctx.board(), [ctx.rack, opp_rack], bag,
               list(ctx.scores), ctx.passes, ME)
    rng = random.Random(iteration_rng(ctx.seed, iteration).random())
    apply_choice(st, candidate_choice(cand), rules, rng)
    for _ in range(END_PLIES if ctx.plies <= 0 else ctx.plies):
        if st.over:
            break
        p = st.to_move
        model = ctx.opponent_model if p == OPP else PERFECT
        ch = choose(st.board, st.racks[p], len(st.bag), dictionary, leave, rules, model, rng,
                    ctx.human_top_n, ctx.human_temperature)
        apply_choice(st, ch, rules, rng)

    margin = st.scores[ME] - st.scores[OPP]
    if st.over:
        return (1.0 if margin > 0 else 0.5 if margin == 0 else 0.0), float(margin)
    bag_empty = not st.bag
    margin_f = margin + leave.value(st.racks[ME], bag_empty) - leave.value(st.racks[OPP], bag_empty)
    unseen = len(st.bag) + len(st.racks[OPP])
    return win.win_prob(margin_f, unseen, st.to_move == ME), margin_f


# --- kandidater ----------------------------------------------------------------

def static_value(m: Move, rules: Rules, leave: LeaveModel, bag_len: int) -> float:
    if m.kind == "play":
        return m.score + leave.value(m.leave, bag_empty=bag_len == 0)
    return leave.value(m.leave, bag_empty=bag_len == 0 and m.kind == "pass")


def select_candidates(board: Board, rack: str, bag_len: int, dictionary: Dictionary,
                      leave: LeaveModel, k: int, include_exchanges: bool = True,
                      include_pass: bool = True, n_exchanges: int = 3) -> list[tuple[Move, float]]:
    """De k bästa läggningarna efter statisk värdering (+ bästa byten och pass)."""
    rules = board.rules
    plays = ranked_plays(board, rack, bag_len, dictionary, leave)
    plays.sort(key=lambda c: (-c.value, -c.score))
    out: list[tuple[Move, float]] = []
    for c in plays[:max(1, k)]:
        pl = tuple(sorted(Placement(*t) for t in c.placements))
        res = board.evaluate(pl)
        w = res.main_word
        m = Move("play", pl, c.score, w.text, w.row, w.col, w.horizontal,
                 leave=_remove(rack, c.used))
        out.append((m, c.value))
    if include_exchanges and rack and bag_len >= rules.exchange_min_bag:
        exs = [(m, leave.value(m.leave)) for m in generate_exchanges(rack)]
        exs.sort(key=lambda x: -x[1])
        out += exs[:n_exchanges]
    if include_pass:
        m = Move("pass", leave=rack)
        out.append((m, static_value(m, rules, leave, bag_len)))
    return out


# --- statistik -----------------------------------------------------------------

@dataclass
class CandidateStats:
    n: int = 0
    sw: float = 0.0
    sw2: float = 0.0
    sm: float = 0.0
    sm2: float = 0.0
    pruned: bool = False
    values: dict = field(default_factory=dict)      # iteration -> (vinst, marginal)

    def add(self, iteration: int, w: float, m: float) -> None:
        if iteration in self.values:
            return
        self.values[iteration] = (w, m)
        self.n += 1
        self.sw += w; self.sw2 += w * w
        self.sm += m; self.sm2 += m * m

    @staticmethod
    def _se(n, s, s2):
        if n < 2:
            return None
        var = max(0.0, (s2 - s * s / n) / (n - 1))
        return math.sqrt(var / n)

    @property
    def win(self):
        return self.sw / self.n if self.n else None

    @property
    def margin(self):
        return self.sm / self.n if self.n else None

    @property
    def win_se(self):
        return self._se(self.n, self.sw, self.sw2)

    @property
    def margin_se(self):
        return self._se(self.n, self.sm, self.sm2)


def sort_key(st: CandidateStats, sort: str):
    if st.n == 0:
        return (1, 0, 0)
    if sort == "margin":
        return (0, -st.margin, -st.win)
    return (0, -st.win, -st.margin)


def prune(stats: list[CandidateStats], sort: str = "win", min_n: int = 30, z: float = 3.0) -> list[int]:
    """Gallrar kandidater som parvis (samma iterationer) är klart sämre än den bästa.
    Ger index för nyss gallrade."""
    active = [i for i, s in enumerate(stats) if not s.pruned and s.n >= min_n]
    if len(active) < 2:
        return []
    best = min(active, key=lambda i: sort_key(stats[i], sort))
    idx = 1 if sort == "margin" else 0
    eps = 0.5 if sort == "margin" else 0.002
    newly = []
    bv = stats[best].values
    for i in active:
        if i == best:
            continue
        common = [it for it in stats[i].values if it in bv]
        n = len(common)
        if n < min_n:
            continue
        d = [bv[it][idx] - stats[i].values[it][idx] for it in common]
        mean = sum(d) / n
        var = sum((x - mean) ** 2 for x in d) / (n - 1)
        se = math.sqrt(var / n)
        if mean > eps and mean > z * se:
            stats[i].pruned = True
            newly.append(i)
    return newly
