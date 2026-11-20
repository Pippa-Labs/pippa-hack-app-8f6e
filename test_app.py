"""Tests for Rent Check. Run them with `pytest`.

Publishing runs them, and a repository whose tests fail does not deploy.
No test touches the network (conftest.py refuses every socket): the app
never needs it, because the ONS figures ship beside it in
ons_london_rents.json and the place names in london_places.json.

Each example question below is what a person would type, next to the inputs
Pippa's model would pull out of it. The expected verdicts were worked out by
hand from ons_london_rents.json and the bands in app.py:

    below -10%  cheap      -10% to 15%  fair      15% to 35%  high      over 35%  very high

and every rent was picked well inside its band, never on an edge.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from pippa_agentapp_sdk import LocalRunner

import app as app_module
from app import App

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
HERE = Path(app_module.__file__).resolve().parent
RENTS = json.loads((HERE / "ons_london_rents.json").read_text(encoding="utf-8"))
PLACES = json.loads((HERE / "london_places.json").read_text(encoding="utf-8"))

PRIVACY = "Rent Check was given only these details, nothing about who you are."
CAVEAT = ("ONS figures cover all current tenancies, not just new listings, "
          "so newly advertised places usually cost a bit more.")
ASSUMED_ROOM = "You didn't say what kind of place, so I've assumed a room."
COVERS = "Rent Check covers the 32 London boroughs and the City of London"

DATA_KEYS = {
    "verdict", "borough", "property_type", "rent_per_month", "typical_rent_per_month",
    "difference_per_month", "difference_percent", "ons_period", "estimated", "caveat",
    "assumptions", "nearby_boroughs", "inputs_received",
}
OPTIONAL_INTEGERS = {"rent_per_month", "typical_rent_per_month",
                     "difference_per_month", "difference_percent"}
ALWAYS = DATA_KEYS - OPTIONAL_INTEGERS
BOROUGH_COUNT = 33          # 32 boroughs and the City of London


def call(inputs: dict, explicit: bool = False):
    return LocalRunner(App()).call(
        "rent.check", inputs, granted_secrets={}, now=NOW, request_id="test-1",
        explicit=explicit,
    ).result


def ask(rent="", area="", property_type=""):
    return call({"rent": rent, "area": area, "property_type": property_type})


def pounds(amount: int) -> str:
    return f"£{amount:,}"


def last_line_is_the_privacy_line(narrative: str) -> bool:
    return narrative.endswith(PRIVACY) and narrative.splitlines()[-1] == PRIVACY


# ── The manifest ─────────────────────────────────────────────────────────────

def test_the_manifest_is_valid():
    app = App()
    assert app.manifest.app_id == "hack.app_8f6e"
    assert [o.id for o in app.manifest.outcomes] == ["rent.check"]


def test_the_manifest_declares_the_contract():
    manifest = yaml.safe_load((HERE / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["app"]["name"] == "Rent Check"
    assert manifest["app"]["version"] == "0.1.2"
    assert manifest["persistence"] == "none"
    (outcome,) = manifest["outcomes"]
    assert [(i["name"], i["type"], i["required"]) for i in outcome["inputs"]] == [
        ("rent", "string", False), ("area", "string", False), ("property_type", "string", False),
    ]
    output = {f["name"]: f for f in outcome["output"]}
    assert set(output) == DATA_KEYS
    assert {name for name, f in output.items() if f.get("required", True) is False} == OPTIONAL_INTEGERS
    assert {name for name, f in output.items() if f["type"] == "integer"} == OPTIONAL_INTEGERS
    assert output["estimated"]["type"] == "boolean"
    for name in ("assumptions", "nearby_boroughs", "inputs_received"):
        assert output[name]["type"] == "array" and output[name]["item_type"] == "string"


# ── Example questions, as people type them ───────────────────────────────────

#: (what the person typed, the inputs Pippa's model pulls out of it,
#:  expected verdict, expected borough, expected property_type)
EXAMPLES = [
    ("is £1,100 a month fair for a room in Hammersmith?",
     {"rent": "£1,100 a month", "area": "Hammersmith", "property_type": "room"},
     "fair", "Hammersmith and Fulham", "room"),             # 1,100 v 1,017 (estimated): +8%
    ("would 1.1k be fair for a double room in fulham",
     {"rent": "1.1k", "area": "fulham", "property_type": "double room"},
     "fair", "Hammersmith and Fulham", "room"),
    ("£1100pcm for a room in hammersmith, is that fair",
     {"rent": "£1100pcm", "area": "hammersmith", "property_type": "room"},
     "fair", "Hammersmith and Fulham", "room"),
    ("is £250 a week fair for a room in Hammersmtih",
     {"rent": "£250 a week", "area": "Hammersmtih", "property_type": "room"},
     "fair", "Hammersmith and Fulham", "room"),             # 1,083 a month v 1,017: +7%
    ("250pw for a studio in hackney is that cheap",
     {"rent": "250pw", "area": "hackney", "property_type": "studio"},
     "cheap", "Hackney", "studio"),                         # 1,083 v 1,690: -36%
    ("£13,200 a year for a studio in Wandswroth, fair?",
     {"rent": "£13,200 a year", "area": "Wandswroth", "property_type": "studio"},
     "cheap", "Wandsworth", "studio"),                      # 1,100 v 1,389: -21%
    ("am i paying too much at £3,400 a month for a one-bedroom flat in Kensingtn",
     {"rent": "£3,400 a month", "area": "Kensingtn", "property_type": "one-bedroom flat"},
     "high", "Kensington and Chelsea", "1-bed"),            # 3,400 v 2,691: +26%
    ("£1,600 a month for a room in Ken, is that a rip off",
     {"rent": "£1,600 a month", "area": "Ken", "property_type": "room"},
     "very high", "Kensington and Chelsea", "room"),        # 1,600 v 1,131: +41%
    ("is £2,900 pcm fair for a 2 bed flat in Southwork",
     {"rent": "£2,900 pcm", "area": "Southwork", "property_type": "2 bed flat"},
     "high", "Southwark", "2-bed"),                         # 2,900 v 2,409: +20%
    ("£2,400 a month for a 2 bed in Peckham, good price?",
     {"rent": "£2,400 a month", "area": "Peckham", "property_type": "2 bed"},
     "fair", "Southwark", "2-bed"),                         # 2,400 v 2,409: -0.4%
    ("is £2,000 a month a fair rent for a studio in Shoreditch",
     {"rent": "£2,000 a month", "area": "Shoreditch", "property_type": "studio"},
     "high", "Hackney", "studio"),                          # 2,000 v 1,690: +18%
    ("£1,500 for a 1 bed flat in Brixton, is that a good deal",
     {"rent": "£1,500", "area": "Brixton", "property_type": "1 bed"},
     "cheap", "Lambeth", "1-bed"),                          # 1,500 v 1,905: -21%
    ("is £4,500 a month too much for a 3-bed house in Camden",
     {"rent": "£4,500 a month", "area": "Camden", "property_type": "3-bed house"},
     "very high", "Camden", "3-bed"),                       # 4,500 v 3,083: +46%
    ("£5,000 a month for a 5 bedroom house in Barnet, fair?",
     {"rent": "£5,000 a month", "area": "Barnet", "property_type": "5 bedroom house"},
     "very high", "Barnet", "4+ bed"),                      # 5,000 v 3,212: +56%
    ("how does £4,000 a month for a 4+ bed in Ealing compare",
     {"rent": "£4,000 a month", "area": "Ealing", "property_type": "4+ bed"},
     "high", "Ealing", "4+ bed"),                           # 4,000 v 3,326: +20%
    ("is £1,000 a month fair in Croydon",
     {"rent": "£1,000 a month", "area": "Croydon", "property_type": ""},
     "high", "Croydon", "room"),                            # assumed a room: 1,000 v 776: +29%
    ("is £2,000 a month fair for a flat in Lewisham",
     {"rent": "£2,000 a month", "area": "Lewisham", "property_type": "flat"},
     "fair", "Lewisham", "all properties"),                 # 2,000 v 1,838: +9%
    ("is 1100 ok for a room in lewisham",
     {"rent": "1100", "area": "lewisham", "property_type": "room"},
     "high", "Lewisham", "room"),                           # 1,100 v 921: +19%
    ("is £280 fair for a room in Camden",
     {"rent": "£280", "area": "Camden", "property_type": "room"},
     "fair", "Camden", "room"),                             # under £500, so weekly: 1,213 v 1,113: +9%
    ("is £2,500 a month fair for a 1 bed in the City of London",
     {"rent": "£2,500 a month", "area": "City of London", "property_type": "1 bed"},
     "high", "City of London", "1-bed"),                    # 2,500 v 2,097 (estimated): +19%
    ("£750 a month for a room in Twickenham, is that fair",
     {"rent": "£750 a month", "area": "Twickenham", "property_type": "room"},
     "cheap", "Richmond upon Thames", "room"),              # 750 v 878 (estimated): -15%
    ("is £1,000 a month a fair price for a room in London",
     {"rent": "£1,000 a month", "area": "London", "property_type": "room"},
     "fair", "London", "room"),                             # 1,000 v 942 (all London): +6%
    ("what's the going rate for a studio in Islington",
     {"rent": "", "area": "Islington", "property_type": "studio"},
     "", "Islington", "studio"),                            # no rent: typical only
    ("is £1,100 a month fair for a room in Narnia",
     {"rent": "£1,100 a month", "area": "Narnia", "property_type": "room"},
     "", "", ""),
    ("is £1,200 a month fair for a 2 bed flat in Watford",
     {"rent": "£1,200 a month", "area": "Watford", "property_type": "2 bed flat"},
     "", "", ""),
]
EXAMPLE_IDS = [question for question, *_ in EXAMPLES]


@pytest.mark.parametrize("question, inputs, verdict, borough, property_type", EXAMPLES,
                         ids=EXAMPLE_IDS)
def test_example_questions(question, inputs, verdict, borough, property_type):
    result = call(inputs)
    assert result.data["verdict"] == verdict
    assert result.data["borough"] == borough
    assert result.data["property_type"] == property_type
    assert last_line_is_the_privacy_line(result.narrative)
    if verdict:
        # Pippa's reply comes from the narrative: it must hold the whole answer.
        assert result.narrative.startswith(verdict.capitalize() + ".")
        assert borough in result.narrative
        assert pounds(result.data["typical_rent_per_month"]) in result.narrative
        word = "above" if result.data["difference_per_month"] > 0 else "below"
        assert word in result.narrative


@pytest.mark.parametrize("question, inputs, verdict, borough, property_type", EXAMPLES,
                         ids=EXAMPLE_IDS)
def test_every_example_answers_well_inside_20_seconds(question, inputs, verdict, borough,
                                                      property_type):
    started = time.perf_counter()
    call(inputs)
    assert time.perf_counter() - started < 2


@pytest.mark.parametrize("question, inputs, verdict, borough, property_type", EXAMPLES,
                         ids=EXAMPLE_IDS)
def test_the_data_has_the_declared_keys_and_types(question, inputs, verdict, borough,
                                                  property_type):
    data = call(inputs).data
    assert ALWAYS <= set(data) <= DATA_KEYS
    for name in OPTIONAL_INTEGERS & set(data):
        assert type(data[name]) is int
    assert type(data["estimated"]) is bool
    for name in ("verdict", "borough", "property_type", "ons_period", "caveat"):
        assert isinstance(data[name], str)
    for name in ("assumptions", "nearby_boroughs", "inputs_received"):
        assert isinstance(data[name], list) and all(isinstance(x, str) for x in data[name])
    if verdict:
        assert {"rent_per_month", "typical_rent_per_month", "difference_per_month",
                "difference_percent"} <= set(data)


# ── The figures ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("inputs, rent, typical, difference, percent, estimated", [
    ({"rent": "£1,100 a month", "area": "Hammersmith", "property_type": "room"}, 1100, 1017, 83, 8, True),
    ({"rent": "1.1k", "area": "Hammersmith", "property_type": "room"}, 1100, 1017, 83, 8, True),
    ({"rent": "£13,200 a year", "area": "Wandsworth", "property_type": "studio"}, 1100, 1389, -289, -21, False),
    ({"rent": "£1,600 a month", "area": "Ken", "property_type": "room"}, 1600, 1131, 469, 41, False),
    ({"rent": "£2,400 a month", "area": "Peckham", "property_type": "2 bed"}, 2400, 2409, -9, 0, False),
    ({"rent": "£4,500 a month", "area": "Camden", "property_type": "3-bed house"}, 4500, 3083, 1417, 46, False),
    ({"rent": "£1,000 a month", "area": "Croydon", "property_type": ""}, 1000, 776, 224, 29, False),
    ({"rent": "£2,000 a month", "area": "Lewisham", "property_type": "flat"}, 2000, 1838, 162, 9, False),
    ({"rent": "£2,500 a month", "area": "City of London", "property_type": "1 bed"}, 2500, 2097, 403, 19, True),
    ({"rent": "£750 a month", "area": "Twickenham", "property_type": "room"}, 750, 878, -128, -15, True),
])
def test_the_figures(inputs, rent, typical, difference, percent, estimated):
    result = call(inputs)
    assert result.data["rent_per_month"] == rent
    assert result.data["typical_rent_per_month"] == typical
    assert result.data["difference_per_month"] == difference
    assert result.data["difference_percent"] == percent
    assert result.data["estimated"] is estimated
    assert result.data["ons_period"] == RENTS["period_label"] == "October 2026"
    assert pounds(typical) in result.narrative


@pytest.mark.parametrize("text, monthly", [
    ("£1,100 a month", 1100),
    ("1.1k", 1100),
    ("£1100pcm", 1100),
    ("£1,100", 1100),
    ("1100", 1100),
    ("£250 a week", 1083),      # 250 x 52 / 12 = 1,083.33
    ("250pw", 1083),
    ("£13,200 a year", 1100),
    ("£280", 1213),             # under £500 with no period: read as weekly
])
def test_rents_people_write(text, monthly):
    assert ask(text, "Camden", "room").data["rent_per_month"] == monthly


def test_a_small_rent_with_no_period_is_read_as_weekly_and_says_so():
    result = ask("£280", "Camden", "room")
    assert result.data["rent_per_month"] == 1213
    assert any("week" in line.lower() for line in result.data["assumptions"])


def test_the_difference_is_negative_below_and_positive_above():
    below = ask("£1,500 a month", "Brixton", "1 bed").data
    assert below["difference_per_month"] == 1500 - 1905
    assert below["difference_percent"] == -21
    above = ask("£2,900 pcm", "Southwark", "2 bed flat").data
    assert above["difference_per_month"] == 2900 - 2409
    assert above["difference_percent"] == 20
    assert "below" in ask("£1,500 a month", "Brixton", "1 bed").narrative
    assert "above" in ask("£2,900 pcm", "Southwark", "2 bed flat").narrative


@pytest.mark.parametrize("rent, verdict", [
    ("£1,850 a month", "cheap"),        # -10.6%
    ("£1,870 a month", "fair"),         #  -9.6%
    ("£2,370 a month", "fair"),         # +14.5%
    ("£2,390 a month", "high"),         # +15.5%
    ("£2,780 a month", "high"),         # +34.4%
    ("£2,810 a month", "very high"),    # +35.8%
])
def test_either_side_of_each_band_edge(rent, verdict):
    # A 1-bed in Camden: ONS says £2,069.
    result = ask(rent, "Camden", "1 bed")
    assert result.data["typical_rent_per_month"] == 2069
    assert result.data["verdict"] == verdict
    assert result.narrative.startswith(verdict.capitalize() + ".")


# ── Places ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("area, borough", [
    ("Hammersmith", "Hammersmith and Fulham"),
    ("Hammersmtih", "Hammersmith and Fulham"),
    ("hammersmith & fulham", "Hammersmith and Fulham"),
    ("Ken", "Kensington and Chelsea"),
    ("Kensington", "Kensington and Chelsea"),
    ("Kensingtn", "Kensington and Chelsea"),
    ("Kennington", "Lambeth"),
    ("Wandswroth", "Wandsworth"),
    ("Southwork", "Southwark"),
    ("Peckham", "Southwark"),
    ("Shoreditch", "Hackney"),
    ("Brixton", "Lambeth"),
    ("Twickenham", "Richmond upon Thames"),
    ("the City", "City of London"),
    ("Camden Town", "Camden"),
    ("  peckham  ", "Southwark"),
])
def test_places_people_write(area, borough):
    result = ask("", area, "room")
    assert result.data["borough"] == borough
    assert result.data["nearby_boroughs"] == []


def test_an_unknown_place_gets_a_polite_reply_with_suggestions():
    result = ask("£1,100 a month", "Narnia", "room")
    data = result.data
    assert data["verdict"] == "" and data["borough"] == "" and data["property_type"] == ""
    assert not OPTIONAL_INTEGERS & set(data)
    assert data["nearby_boroughs"]
    assert all(b in RENTS["boroughs"] for b in data["nearby_boroughs"])
    assert data["caveat"] == "" and data["ons_period"] == "" and data["estimated"] is False
    assert "Narnia" in result.narrative
    assert COVERS in result.narrative
    assert last_line_is_the_privacy_line(result.narrative)


def test_a_town_outside_london_gets_the_nearest_boroughs():
    result = ask("£1,200 a month", "Watford", "2 bed flat")
    assert result.data["borough"] == ""
    assert result.data["verdict"] == ""
    assert result.data["nearby_boroughs"] == ["Harrow", "Hillingdon", "Barnet"]
    assert "outside london" in result.narrative.lower()
    assert "Watford" in result.narrative
    assert last_line_is_the_privacy_line(result.narrative)


def test_a_region_of_london_gets_suggestions():
    result = ask("£1,500 a month", "south london", "studio")
    assert result.data["nearby_boroughs"]
    assert all(b in RENTS["boroughs"] for b in result.data["nearby_boroughs"])
    assert last_line_is_the_privacy_line(result.narrative)


def test_no_area_at_all_is_answered_plainly():
    result = ask("£1,100 a month", "", "room")
    assert result.data["verdict"] == ""
    assert last_line_is_the_privacy_line(result.narrative)


# ── Property types ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, kind", [
    ("room", "room"),
    ("double room", "room"),
    ("studio", "studio"),
    ("1 bed", "1-bed"),
    ("one-bedroom flat", "1-bed"),
    ("2 bed flat", "2-bed"),
    ("3-bed house", "3-bed"),
    ("4+ bed", "4+ bed"),
    ("5 bedroom house", "4+ bed"),
    ("flat", "all properties"),
    ("house", "all properties"),
    ("apartment", "all properties"),
    ("", "room"),
])
def test_property_types_people_write(text, kind):
    assert ask("", "Camden", text).data["property_type"] == kind


@pytest.mark.parametrize("missing", ["", None, "absent"])
def test_no_property_type_assumes_a_room_and_says_so(missing):
    inputs = {"rent": "£1,000 a month", "area": "Croydon"}
    if missing != "absent":
        inputs["property_type"] = missing
    result = call(inputs)
    assert result.data["property_type"] == "room"
    assert result.data["typical_rent_per_month"] == 776
    assert ASSUMED_ROOM in result.data["assumptions"]
    assert ASSUMED_ROOM in result.narrative


@pytest.mark.parametrize("text", ["flat", "house", "apartment"])
def test_a_flat_with_no_bedrooms_compares_with_all_properties(text):
    result = ask("£2,000 a month", "Lewisham", text)
    assert result.data["property_type"] == "all properties"
    assert result.data["typical_rent_per_month"] == RENTS["boroughs"]["Lewisham"]["all"] == 1838
    assert any(line.startswith("You didn't say how many bedrooms")
               for line in result.data["assumptions"])
    assert ASSUMED_ROOM not in result.data["assumptions"]


# ── No rent given ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("missing", ["", "   ", None, "absent"])
def test_no_rent_gives_the_typical_rent_and_no_verdict(missing):
    inputs = {"area": "Islington", "property_type": "studio"}
    if missing != "absent":
        inputs["rent"] = missing
    result = call(inputs)
    data = result.data
    assert data["verdict"] == ""
    assert data["typical_rent_per_month"] == 1549
    assert not {"rent_per_month", "difference_per_month", "difference_percent"} & set(data)
    assert data["caveat"] == CAVEAT
    assert data["ons_period"] == "October 2026"
    assert "£1,549" in result.narrative and "Islington" in result.narrative
    assert last_line_is_the_privacy_line(result.narrative)


# ── Cells ONS does not publish ───────────────────────────────────────────────

@pytest.mark.parametrize("area, kind, typical", [
    ("Hammersmith and Fulham", "room", 1017),
    ("Richmond upon Thames", "room", 878),
    ("Bexley", "room", 859),
    ("Lambeth", "room", 948),
    ("Sutton", "room", 828),
    ("City of London", "room", 1057),
    ("City of London", "studio", 1552),
    ("City of London", "1 bed", 2097),
    ("City of London", "2 bed", 2632),
    ("City of London", "3 bed", 3030),
    ("City of London", "4+ bed", 4046),
    ("City of London", "flat", 2743),
])
def test_a_missing_ons_figure_is_estimated_from_the_neighbours(area, kind, typical):
    result = ask("", area, kind)
    assert result.data["typical_rent_per_month"] == typical
    assert result.data["estimated"] is True
    assert pounds(typical) in result.narrative


def test_every_published_figure_is_used_as_it_is():
    kinds = {"room": "room", "studio": "studio", "1bed": "1 bed", "2bed": "2 bed",
             "3bed": "3 bed", "4plus": "4+ bed", "all": "flat"}
    checked = 0
    for borough, row in RENTS["boroughs"].items():
        for key, text in kinds.items():
            if row[key] is None:
                continue
            data = ask("", borough, text).data
            assert (data["borough"], data["typical_rent_per_month"], data["estimated"]) == \
                (borough, row[key], False), (borough, key)
            checked += 1
    assert len(RENTS["boroughs"]) == BOROUGH_COUNT
    assert checked > 200


# ── What every answer carries ────────────────────────────────────────────────

EVERY_BRANCH = [
    {"rent": "£1,100 a month", "area": "Hammersmith", "property_type": "room"},   # full, estimated
    {"rent": "£2,900 pcm", "area": "Southwark", "property_type": "2 bed flat"},   # full
    {"rent": "£280", "area": "Camden", "property_type": "room"},                  # weekly assumed
    {"rent": "£1,000 a month", "area": "Croydon", "property_type": ""},           # room assumed
    {"rent": "£2,000 a month", "area": "Lewisham", "property_type": "flat"},      # all properties
    {"rent": "", "area": "Islington", "property_type": "studio"},                 # no rent
    {"rent": "£1,000 a month", "area": "London", "property_type": "room"},        # London-wide
    {"rent": "£1,100 a month", "area": "Narnia", "property_type": "room"},        # unknown place
    {"rent": "£1,200 a month", "area": "Watford", "property_type": "2 bed flat"}, # outside London
    {"rent": "£1,500 a month", "area": "south london", "property_type": "studio"},  # region
    {"rent": "£1,100 a month", "area": "", "property_type": "room"},              # no area
    {"rent": "", "area": "", "property_type": ""},                                # nothing at all
    {},                                                                           # nothing sent
    {"rent": None, "area": None, "property_type": None},
    {"rent": "lots", "area": "Camden", "property_type": "room"},                  # unreadable rent
    {"rent": "£", "area": "Camden", "property_type": "room"},
    {"rent": "0", "area": "Camden", "property_type": "room"},
    {"rent": "-500", "area": "Camden", "property_type": "room"},
    {"rent": "£1,100,000,000 a month", "area": "Camden", "property_type": "room"},
    {"rent": "£1,100 a month", "area": "!!!", "property_type": "room"},
    {"rent": "£1,100 a month", "area": "Camden", "property_type": "spaceship"},
    {"rent": "£1,100 a month", "area": "x" * 500, "property_type": "room"},
]


@pytest.mark.parametrize("inputs", EVERY_BRANCH)
def test_every_answer_ends_with_the_privacy_line(inputs):
    result = call(inputs)          # never raises, whatever was typed
    assert isinstance(result.narrative, str) and result.narrative.strip()
    assert last_line_is_the_privacy_line(result.narrative)
    assert result.narrative.count(PRIVACY) == 1


@pytest.mark.parametrize("inputs", EVERY_BRANCH)
def test_the_caveat_comes_with_every_typical_rent(inputs):
    result = call(inputs)
    data = result.data
    if "typical_rent_per_month" in data:
        assert data["caveat"] == CAVEAT
        assert data["ons_period"] == "October 2026"
        assert CAVEAT in result.narrative
    else:
        assert data["caveat"] == ""
        assert data["ons_period"] == ""
        assert data["verdict"] == ""


@pytest.mark.parametrize("inputs, received", [
    ({"rent": "£1,100 a month", "area": "Hammersmith", "property_type": "room"},
     ["rent: £1,100 a month", "area: Hammersmith", "property_type: room"]),
    ({"rent": "  £1,100 a month  ", "area": " Hammersmith", "property_type": "room "},
     ["rent: £1,100 a month", "area: Hammersmith", "property_type: room"]),
    ({"rent": "£1,100 a month", "area": "Hammersmith", "property_type": ""},
     ["rent: £1,100 a month", "area: Hammersmith"]),
    ({"rent": None, "area": "Hammersmith", "property_type": None},
     ["area: Hammersmith"]),
    ({"area": "Hammersmith"},
     ["area: Hammersmith"]),
    ({"rent": "   ", "area": "Peckham", "property_type": "studio"},
     ["area: Peckham", "property_type: studio"]),
    ({"property_type": "studio", "area": "Peckham", "rent": "250pw"},
     ["rent: 250pw", "area: Peckham", "property_type: studio"]),
    ({"rent": "£1,100 a month", "area": "Narnia", "property_type": "room"},
     ["rent: £1,100 a month", "area: Narnia", "property_type: room"]),
    ({}, []),
    ({"rent": "", "area": "", "property_type": ""}, []),
])
def test_inputs_received_lists_exactly_what_was_given(inputs, received):
    assert call(inputs).data["inputs_received"] == received


def test_picked_by_name_gives_the_same_answer():
    inputs = {"rent": "£1,100 a month", "area": "Hammersmith", "property_type": "room"}
    by_name = call(inputs, explicit=True)
    assert by_name.data == call(inputs).data
    assert by_name.narrative == call(inputs).narrative


def test_the_brief_example_in_full():
    result = ask("£1,100 a month", "Hammersmith", "room")
    assert result.data == {
        "verdict": "fair",
        "borough": "Hammersmith and Fulham",
        "property_type": "room",
        "rent_per_month": 1100,
        "typical_rent_per_month": 1017,
        "difference_per_month": 83,
        "difference_percent": 8,
        "ons_period": "October 2026",
        "estimated": True,
        "caveat": CAVEAT,
        "assumptions": result.data["assumptions"],
        "nearby_boroughs": [],
        "inputs_received": ["rent: £1,100 a month", "area: Hammersmith", "property_type: room"],
    }
    assert ASSUMED_ROOM not in result.data["assumptions"]
    assert result.narrative.startswith("Fair.")
    assert "£1,017" in result.narrative and "£1,100" in result.narrative
    assert "Hammersmith and Fulham" in result.narrative
    assert "above" in result.narrative
    assert CAVEAT in result.narrative
    assert last_line_is_the_privacy_line(result.narrative)


# ── Regressions found while building ─────────────────────────────────────────

@pytest.mark.parametrize("text, monthly", [
    ("£4,800pcm", 4800),        # a comma before letters once lost the thousands
    ("£1,100pcm", 1100),
    ("£1,250pw", 5417),
    ("£1 100", 1100),
])
def test_thousands_written_right_up_against_the_period(text, monthly):
    assert ask(rent=text, area="Kensington", property_type="2 bed").data["rent_per_month"] == monthly


@pytest.mark.parametrize("text, kind", [
    ("room in a 3 bed flat", "room"),
    ("double room in a house share", "room"),
    ("2b2b", "2-bed"),
])
def test_property_types_found_while_building(text, kind):
    assert ask(rent="£1,000", area="Hackney", property_type=text).data["property_type"] == kind


def test_a_compass_short_region_gets_its_boroughs():
    result = ask(rent="£2,000", area="SW London", property_type="1 bed")
    assert result.data["verdict"] == ""
    assert "Wandsworth" in result.data["nearby_boroughs"]
    assert result.narrative.startswith("SW London covers several boroughs")
    assert last_line_is_the_privacy_line(result.narrative)
