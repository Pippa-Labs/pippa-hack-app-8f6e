"""Rent Check: is a London rent cheap, fair, high or very high?

One job: compare the rent a person names with the official ONS figure for
that London borough and property type. Everything it needs ships beside this
file (ons_london_rents.json, london_places.json), so it calls no API, keeps
nothing between calls and answers in milliseconds.

Pippa's model fills three string inputs from the person's message, as they
wrote them (`rent`, `area`, `property_type`); this file does the messy part:
"1.1k", "£1100pcm", "£250 a week", "Kensingtn", "Ken", "Peckham", "Narnia".
"""

from __future__ import annotations

import difflib
import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from pippa_agentapp_sdk import (
    AgentAppError,
    Call,
    Manifest,
    Result,
    load_manifest_file,
    validate_manifest,
)

MANIFEST_PATH = Path(__file__).with_name("manifest.yaml")
RENTS = json.loads(Path(__file__).with_name("ons_london_rents.json").read_text("utf-8"))
PLACES = json.loads(Path(__file__).with_name("london_places.json").read_text("utf-8"))

OUTCOME = "rent.check"
INPUT_NAMES = ("rent", "area", "property_type")

PRIVACY_LINE = "Rent Check was given only these details, nothing about who you are."
CAVEAT = "ONS covers all current tenancies, so new listings usually cost a bit more."
NO_TYPE = "You didn't say what kind of place, so I've assumed a room."
COVERAGE = "Rent Check covers the 32 London boroughs and the City of London."

#: The narrative is one short paragraph: Pippa writes her reply around it, and
#: CLAUDE.md describes it as "one plain sentence Pippa may use". A long,
#: multi-line narrative is the one thing about a reply this app controls, so it
#: is kept to a few sentences with no line breaks, and the person's own words
#: are quoted back at most this long.
QUOTE_MAX = 40
NARRATIVE_MAX = 500
FALLBACK_NARRATIVE = ("Tell me the rent and the London borough, for example "
                      "\"£1,100 a month for a room in Hackney\", and I'll check it "
                      "against ONS figures.")

#: Verdict bands on (rent - typical) / typical, in percent. The fair band
#: reaches further above the figure than below it because ONS covers every
#: current tenancy, and new lets usually cost more than the stock average.
CHEAP_BELOW = Decimal(-10)
FAIR_UP_TO = Decimal(15)
HIGH_UP_TO = Decimal(35)

#: A monthly London rent under this is not plausible, so an amount with no
#: period below it is read as weekly (and the reply says so).
WEEKLY_IF_UNDER = Decimal(500)
MIN_MONTHLY, MAX_MONTHLY = 100, 100_000

TYPE_LABEL = {
    "room": "room", "studio": "studio", "1bed": "1-bed", "2bed": "2-bed",
    "3bed": "3-bed", "4plus": "4+ bed", "all": "all properties",
}
TYPE_PHRASE = {
    "room": "a room", "studio": "a studio", "1bed": "a 1-bed", "2bed": "a 2-bed",
    "3bed": "a 3-bed", "4plus": "a 4+ bed", "all": "a home",
}
VERDICT_SENTENCE = {"cheap": "Cheap.", "fair": "Fair.", "high": "High.", "very high": "Very high."}

#: Default suggestions when an unknown place resembles no borough at all.
DEFAULT_SUGGESTIONS = ["Westminster", "Camden", "Hackney", "Lambeth", "Tower Hamlets"]


class App:
    """Compare a London rent with the ONS figure for its borough and type."""

    def __init__(self) -> None:
        self._manifest = validate_manifest(load_manifest_file(MANIFEST_PATH))

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    def handle(self, call: Call) -> Result:
        if call.outcome_id != OUTCOME:
            raise AgentAppError(f"this app cannot do {call.outcome_id!r}")
        given = _given(call.inputs or {})
        received = [f"{name}: {value}" for name, value in given.items()]
        data, sentences = _answer(given)
        data["inputs_received"] = received
        return Result(data=data, narrative=_narrative(sentences))


def _narrative(sentences: list) -> str:
    """One paragraph, never empty, at most NARRATIVE_MAX characters.

    The answer comes first and the caveat and privacy sentence last, always.
    The notes in between (an estimate, an assumption) are kept in order while
    they fit; every one of them is also in data["assumptions"] or
    data["estimated"], so nothing is lost when a pile-up of them is trimmed.
    The exact inputs are in data["inputs_received"].
    """
    sentences = [" ".join(str(s).split()) for s in sentences if s and str(s).strip()]
    first, rest = (sentences[0], sentences[1:]) if sentences else (FALLBACK_NARRATIVE, [])
    tail = [s for s in rest if s == CAVEAT] + [PRIVACY_LINE]
    room = NARRATIVE_MAX - len(" ".join([first, *tail]))
    kept = []
    for sentence in rest:
        if sentence != CAVEAT and len(sentence) + 1 <= room:
            kept.append(sentence)
            room -= len(sentence) + 1
    return " ".join([first, *kept, *tail])


# ── The answer ───────────────────────────────────────────────────────────────

def _answer(given: dict) -> tuple[dict, list]:
    """Build `data` (without inputs_received) and the narrative's lines."""
    data = {
        "verdict": "", "borough": "", "property_type": "", "ons_period": "",
        "estimated": False, "caveat": "", "assumptions": [], "nearby_boroughs": [],
    }
    area_text = given.get("area", "")
    place = find_place(area_text)

    if place["kind"] == "empty":
        return data, ["Which London borough is it in? " + FALLBACK_NARRATIVE]
    if place["kind"] == "outside":
        data["nearby_boroughs"] = list(place["boroughs"])
        return data, [f"{_title(place['name'])} is outside London, and {COVERAGE[:-1]} "
                      f"only. The nearest boroughs are {_and_list(place['boroughs'])}."]
    if place["kind"] == "region":
        data["nearby_boroughs"] = list(place["boroughs"])
        return data, [f"{_title(place['name'])} covers several boroughs, and ONS figures "
                      f"are per borough. Which one is it, for example "
                      f"{_or_list(place['boroughs'])}?"]
    if place["kind"] == "unknown":
        data["nearby_boroughs"] = list(place["boroughs"])
        if place["similar"]:
            ask = f"Did you mean {_or_list(place['boroughs'])}?"
        else:
            ask = f"Which borough is it in? For example {_or_list(place['boroughs'])}."
        return data, [f"Sorry, I don't know where \"{_quote(area_text)}\" is. {COVERAGE} {ask}"]

    # A borough, or London as a whole.
    assumptions = []
    if place["kind"] == "london":
        borough, where = "London", "London"
        assumptions.append("You only named London, so this is London as a whole; name a "
                           "borough for a sharper answer.")
    else:
        borough = place["name"]
        where = "the City of London" if borough == "City of London" else borough
        if place.get("fuzzy"):
            assumptions.append(f"I've read \"{_quote(area_text)}\" as {borough}.")
        elif place.get("via_area"):
            assumptions.append(f"{_title(place['matched'])} is in {borough}.")

    kind, type_note = parse_property_type(given.get("property_type", ""))
    if type_note == "no_count":
        assumptions.append("You didn't say how many bedrooms, so this is the average for "
                           "all property types.")
    elif type_note:
        assumptions.append(type_note)

    typical, estimated_from = typical_rent(borough, kind)
    if typical is None:  # Cannot happen with the shipped data; kept honest anyway.
        data.update(borough=borough, property_type=TYPE_LABEL[kind], assumptions=assumptions)
        return data, [f"ONS publishes no {TYPE_LABEL[kind]} figure for {where}, "
                      f"so I can't compare it."]

    period = RENTS["period_label"]
    data.update(borough=borough, property_type=TYPE_LABEL[kind], ons_period=period,
                typical_rent_per_month=typical, estimated=bool(estimated_from),
                caveat=CAVEAT)
    estimate_line = None
    if estimated_from:
        label = "all-properties" if kind == "all" else TYPE_LABEL[kind]
        estimate_line = (f"ONS publishes no {label} figure for {where} (too few rents "
                         f"recorded), so this is the average for neighbouring boroughs.")

    rent_text = given.get("rent", "")
    monthly, rent_note = parse_rent(rent_text)
    lines = []
    if monthly is None:
        opener = f"I couldn't read a rent in \"{_quote(rent_text)}\". " if rent_text else ""
        lines.append(f"{opener}The typical rent for {TYPE_PHRASE[kind]} in {where} is "
                     f"{_money(typical)} a month (ONS, {period}). Tell me the rent and "
                     f"I'll say whether it's fair.")
    else:
        if rent_note:
            assumptions.append(rent_note)
        diff = monthly - typical
        percent = Decimal(diff) * 100 / Decimal(typical)
        verdict = _verdict(percent)
        shown = _round(percent)
        data.update(verdict=verdict, rent_per_month=monthly,
                    difference_per_month=diff, difference_percent=shown)
        if diff == 0:
            gap = "the same as"
        else:
            size = f"{abs(shown)}%" if shown else "under 1%"
            gap = f"{_money(abs(diff))} ({size}) {'above' if diff > 0 else 'below'}"
        lines.append(f"{VERDICT_SENTENCE[verdict]} {_money(monthly)} a month for "
                     f"{TYPE_PHRASE[kind]} in {where} is {gap} the typical "
                     f"{_money(typical)} a month (ONS, {period}).")

    if estimate_line:
        lines.append(estimate_line)
    lines.extend(assumptions)
    lines.append(CAVEAT)
    data["assumptions"] = assumptions
    return data, lines


def _verdict(percent: Decimal) -> str:
    if percent < CHEAP_BELOW:
        return "cheap"
    if percent <= FAIR_UP_TO:
        return "fair"
    if percent <= HIGH_UP_TO:
        return "high"
    return "very high"


def typical_rent(borough: str, kind: str) -> tuple[int | None, list]:
    """The ONS figure, or the mean of the neighbours' figures when ONS has none.

    Returns (rent, neighbours used); the list is empty for a real ONS figure.
    """
    if borough == "London":
        return RENTS["london"].get(kind), []
    value = RENTS["boroughs"].get(borough, {}).get(kind)
    if value is not None:
        return int(value), []
    used = [n for n in PLACES["boroughs"][borough]["neighbours"]
            if RENTS["boroughs"].get(n, {}).get(kind) is not None]
    if not used:
        return None, []
    total = sum(Decimal(RENTS["boroughs"][n][kind]) for n in used)
    return _round(total / len(used)), used


# ── Inputs ───────────────────────────────────────────────────────────────────

def _given(inputs: dict) -> dict:
    """The inputs actually given: not missing, not blank. Values stripped."""
    given = {}
    for name in INPUT_NAMES:
        value = inputs.get(name)
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text:
            given[name] = text
    return given


def _quote(text: str) -> str:
    """The person's words, on one line and not too long, for quoting back."""
    text = " ".join(str(text).split())
    return text if len(text) <= QUOTE_MAX else text[:QUOTE_MAX - 1].rstrip() + "…"


# ── Rent: "£1,100 a month", "1.1k", "£1100pcm", "£250 a week", "250pw" ────────

_WEEK = re.compile(r"/\s*(?:wk|week)|\bp\s?/?\s?w\b|\bpppw\b|\bper\s+week\b|\ba\s+week\b"
                   r"|\bweekly\b|\bweek\b|\bwk\b|\beach\s+week\b")
_YEAR = re.compile(r"/\s*(?:yr|year|annum)|\bp\s?/?\s?a\b|\bper\s+(?:annum|year)\b|\ba\s+year\b"
                   r"|\byearly\b|\bannual(?:ly)?\b|\byear\b|\byr\b")
_MONTH = re.compile(r"/\s*(?:mo|mth|month)|\bp\s?/?\s?c\s?/?\s?m\b|\bp\s?/?\s?m\b"
                    r"|\bper\s+(?:calendar\s+)?month\b|\ba\s+month\b|\bmonthly\b|\bmonth\b"
                    r"|\bmth\b|\bmo\b")
_AMOUNT = re.compile(r"(£|gbp\s?)?\s?(\d+(?:\.\d+)?)\s*(k|grand|thousand)?\b")
_NOT_MONEY_AFTER = re.compile(r"\s*(?:\+|-)?\s*(?:bed|br\b|b\b|bedroom|room|person|people)")


def parse_rent(text: str) -> tuple[int | None, str]:
    """Return (whole pounds a month, a note for the reply), or (None, "")."""
    if not text:
        return None, ""
    t = text.lower().replace("£ ", "£")
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)      # 1,100 -> 1100
    t = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", "", t)      # 1 100 -> 1100
    t = re.sub(r"(?<=\d)(?=[a-z])", " ", t)            # 1100pcm -> 1100 pcm
    amount = _pick_amount(t)
    if amount is None:
        return None, ""
    period = _period(t)
    note = ""
    if period == "week":
        monthly = amount * 52 / 12
        note = f"{_money(amount)} a week is {_money(_round(monthly))} a month."
    elif period == "year":
        monthly = amount / 12
        note = f"{_money(amount)} a year is {_money(_round(monthly))} a month."
    elif period == "month":
        monthly = amount
    elif amount < WEEKLY_IF_UNDER:
        monthly = amount * 52 / 12
        note = (f"I've read {_money(amount)} as weekly ({_money(_round(monthly))} a month), "
                f"as it's too low for a monthly London rent.")
    else:
        monthly = amount
    pounds = _round(monthly)
    if not MIN_MONTHLY <= pounds <= MAX_MONTHLY:
        return None, ""
    return pounds, note


def _pick_amount(t: str) -> Decimal | None:
    """The money amount in the text: one with £ or k first, else the first number."""
    best = None
    for match in _AMOUNT.finditer(t):
        pound, number, thousands = match.groups()
        if not pound and not thousands and _NOT_MONEY_AFTER.match(t, match.end()):
            continue                                    # "2 bed", "1 room"
        try:
            value = Decimal(number)
        except InvalidOperation:
            continue
        if thousands:
            value *= 1000
        if value <= 0:
            continue
        if pound or thousands:
            return value
        if best is None:
            best = value
    return best


def _period(t: str) -> str | None:
    found = []
    for name, pattern in (("week", _WEEK), ("year", _YEAR), ("month", _MONTH)):
        match = pattern.search(t)
        if match:
            found.append((match.start(), name))
    return min(found)[1] if found else None


# ── Property type ────────────────────────────────────────────────────────────

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "zero": 0}
_BEDS = re.compile(r"\b(\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten)\s*\+?\s*"
                   r"(?:bed(?:room)?s?|bedroomed|br|bd|b)\b")
_FOUR_OR_MORE = re.compile(r"\b(?:4|four)\s*(?:or|\+)\s*(?:more|plus)?\b")
_STUDIO = re.compile(r"\bstudio|\bbed\s?sit")
_ROOM = re.compile(r"\brooms?\b|\bflat\s?share|\bhouse\s?share|\bshared\b|\ben\s?suite"
                   r"|\blodg|\bbedroom\b|\bhmo\b|\bdouble\b|\bsingle\b|\bhouseshare|\bflatshare")
_ROOM_IN = re.compile(r"\b(?:rooms?|double|single|en\s?suite|bedroom)\b.*\bin\b")
_WHOLE = re.compile(r"\b(?:flat|apartment|house|maisonette|home|property|place|duplex"
                    r"|bungalow|cottage|penthouse|terrace|semi)\b")


def parse_property_type(text: str) -> tuple[str, str]:
    """Return (type key, note). The note is "" , "no_count" or a sentence."""
    if not text:
        return "room", NO_TYPE
    t = text.lower().replace("-", " ")
    t = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", t)
    if _ROOM_IN.search(t):                              # "a room in a 3 bed flat"
        return "room", ""
    if _FOUR_OR_MORE.search(t) and re.search(r"bed|room", t):
        return "4plus", ""
    match = _BEDS.search(t)
    if match:
        word = match.group(1)
        count = int(word) if word.isdigit() else _NUMBER_WORDS[word]
        if count == 0:
            return "studio", ""
        return ("4plus" if count >= 4 else f"{count}bed"), ""
    if re.fullmatch(r"\s*\d\s*", t):
        count = int(t)
        return ("studio" if count == 0 else "4plus" if count >= 4 else f"{count}bed"), ""
    if _STUDIO.search(t):
        return "studio", ""
    if _ROOM.search(t):
        return "room", ""
    if _WHOLE.search(t):
        return "all", "no_count"
    return "room", f"I didn't recognise \"{_quote(text)}\" as a property type, so I've assumed a room."


# ── Places: boroughs, short names, neighbourhoods, typos ─────────────────────

def _norm(text: str) -> str:
    t = text.lower().replace("’", "").replace("'", "").replace("-", " ").replace(".", "")
    t = re.sub(r"[^a-z0-9& ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokens(text: str) -> list:
    return re.findall(r"[a-z0-9&]+", _norm(text))


def _build_index() -> tuple[dict, dict]:
    """key -> (tier, priority, payload). Tier 0 London places, 1 outside, 2 regions."""
    places, regions = {}, {}

    def add(key, value):
        key = " ".join(_tokens(key))
        if not key:
            return
        for variant in {key, key.replace(" & ", " and "), key.replace(" and ", " & ")}:
            places.setdefault(variant, value)

    for name, info in PLACES["boroughs"].items():
        add(name, (0, 0, name, False))
        for alias in info["aliases"]:
            add(alias, (0, 0, name, False))
    for name, info in PLACES["boroughs"].items():
        for area in info["areas"]:
            add(area, (0, 1, name, True))
    for town, near in PLACES["outside_london"].items():
        add(town, (1, 0, town, near))
    for region, members in PLACES["regions"].items():
        regions[" ".join(_tokens(region))] = members
    return places, regions


INDEX, REGIONS = _build_index()
_FUZZY_SKIP = {"london", "east", "west", "north", "south", "central", "near", "the", "area",
               "borough", "around", "flat", "room", "road", "street", "station", "and",
               "of", "in", "at", "by", "upon", "thames", "green", "park", "town"}


def find_place(text: str) -> dict:
    """Work out which borough a place is in.

    kind: "empty", "borough" (name, matched, via_area, fuzzy), "london",
    "outside" (name, boroughs), "region" (name, boroughs) or
    "unknown" (boroughs, similar).
    """
    tokens = _tokens(text or "")
    if not tokens:
        return {"kind": "empty"}

    # 1. Exact matches, longest phrase first; a borough or short name beats a
    #    neighbourhood of the same length; earlier in the text wins a tie.
    best = None
    for size in range(min(5, len(tokens)), 0, -1):
        for start in range(len(tokens) - size + 1):
            gram = " ".join(tokens[start:start + size])
            hit = INDEX.get(gram)
            if hit:
                rank = (hit[0], -size, hit[1], start)
                if best is None or rank < best[0]:
                    best = (rank, gram, hit)
    if best:
        _, gram, (tier, _, payload, extra) = best
        if tier == 1:
            return {"kind": "outside", "name": gram, "boroughs": list(extra)}
        return {"kind": "borough", "name": payload, "matched": gram, "via_area": extra}

    # 2. Typos: the closest name to any one-to-three-word stretch of the text.
    fuzzy = _closest(tokens)
    if fuzzy:
        gram, (tier, _, payload, extra) = fuzzy
        if tier == 1:
            return {"kind": "outside", "name": gram, "boroughs": list(extra)}
        return {"kind": "borough", "name": payload, "matched": gram,
                "via_area": extra, "fuzzy": True}

    # 3. Regions, and London itself.
    joined = " ".join(tokens)
    for size in range(min(3, len(tokens)), 0, -1):
        for start in range(len(tokens) - size + 1):
            gram = " ".join(tokens[start:start + size])
            if gram in REGIONS:
                if gram == "london" and joined in {"london", "greater london",
                                                   "anywhere in london", "in london"}:
                    return {"kind": "london"}
                if gram == "london":
                    continue
                return {"kind": "region", "name": gram, "boroughs": REGIONS[gram]}
    if "london" in tokens and len(tokens) <= 3:
        return {"kind": "london"}

    return {"kind": "unknown", **_suggest(tokens)}


def _closest(tokens: list):
    best = None
    for size in (1, 2, 3):
        for start in range(len(tokens) - size + 1):
            words = tokens[start:start + size]
            if size == 1 and (words[0] in _FUZZY_SKIP or len(words[0]) < 4):
                continue
            if words[0] in _FUZZY_SKIP:
                continue
            gram = " ".join(words)
            for key, hit in INDEX.items():
                if len(key) < 4 or key[0] != gram[0]:
                    continue
                score = difflib.SequenceMatcher(None, gram, key).ratio()
                if score >= 0.8 and (best is None or score > best[0]):
                    best = (score, key, hit)
    return (best[1], best[2]) if best else None


def _suggest(tokens: list) -> dict:
    """Boroughs whose names look most like what was typed."""
    scores = {}
    grams = [" ".join(tokens[i:i + n]) for n in (1, 2) for i in range(len(tokens) - n + 1)]
    grams = [g for g in grams if g not in _FUZZY_SKIP]
    for key, (tier, _, payload, _extra) in INDEX.items():
        if tier != 0:
            continue
        for gram in grams:
            score = difflib.SequenceMatcher(None, gram, key).ratio()
            if score > scores.get(payload, 0):
                scores[payload] = score
    similar = [name for name, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s >= 0.7][:3]
    if similar:
        return {"boroughs": similar, "similar": True}
    return {"boroughs": list(DEFAULT_SUGGESTIONS), "similar": False}


# ── Small helpers ────────────────────────────────────────────────────────────

def _round(value) -> int:
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _money(value) -> str:
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"£{int(value):,}"
    return f"£{value:,.2f}"


def _title(text: str) -> str:
    small = {"and", "of", "upon", "by", "the"}
    words = text.split()
    return " ".join(w.upper() if w in {"sw", "se", "nw", "ne"}
                    else w if (i and w in small) else w[:1].upper() + w[1:]
                    for i, w in enumerate(words))


def _and_list(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _or_list(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]
