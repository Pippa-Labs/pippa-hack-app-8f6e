"""Build data/ons_london_rents.json for Rent Check from ONS downloads.

Usage (run with an isolated interpreter):
  python3 -I build_ons_table.py PIPR_XLSX PRMS_XLS MEDQ_XLSX OUT_JSON OUT_APPENDIX_MD

Inputs (downloaded 2026-11-20 from ons.gov.uk):
  PIPR_XLSX  Price Index of Private Rents, UK: monthly price statistics, 18 Nov 2026 edition
  PRMS_XLS   Private rental market summary statistics in England, Oct 2022 - Sep 2023 (final edition)
  MEDQ_XLSX  Private rent price median and quartiles, England and Wales, 18 Nov 2026 (first edition;
             used for comparison only, see SOURCES.md)

Method:
  1bed/2bed/3bed/4plus/all : PIPR "Rental price" columns for the latest month (Oct 2026).
  room/studio              : PRMS median (Oct 2022-Sep 2023) x uplift factor, where
                             factor = PIPR all-properties index (latest month)
                                      / mean PIPR all-properties index (Oct 2022..Sep 2023)
                             for the same borough (London region index for the London row).
  Suppressed / unavailable cells -> null. City of London is not published in PIPR, so it is
  null throughout (no index to uplift its PRMS figures with).
"""
import sys
import datetime as dt
import json
import statistics

import openpyxl
import xlrd

PIPR_PATH, PRMS_PATH, MEDQ_PATH, OUT_JSON, OUT_MD = sys.argv[1:6]

BOROUGHS = {  # ONS code -> ONS name
    "E09000001": "City of London", "E09000002": "Barking and Dagenham", "E09000003": "Barnet",
    "E09000004": "Bexley", "E09000005": "Brent", "E09000006": "Bromley", "E09000007": "Camden",
    "E09000008": "Croydon", "E09000009": "Ealing", "E09000010": "Enfield", "E09000011": "Greenwich",
    "E09000012": "Hackney", "E09000013": "Hammersmith and Fulham", "E09000014": "Haringey",
    "E09000015": "Harrow", "E09000016": "Havering", "E09000017": "Hillingdon",
    "E09000018": "Hounslow", "E09000019": "Islington", "E09000020": "Kensington and Chelsea",
    "E09000021": "Kingston upon Thames", "E09000022": "Lambeth", "E09000023": "Lewisham",
    "E09000024": "Merton", "E09000025": "Newham", "E09000026": "Redbridge",
    "E09000027": "Richmond upon Thames", "E09000028": "Southwark", "E09000029": "Sutton",
    "E09000030": "Tower Hamlets", "E09000031": "Waltham Forest", "E09000032": "Wandsworth",
    "E09000033": "Westminster",
}
LONDON = "E12000007"
TYPES = ["room", "studio", "1bed", "2bed", "3bed", "4plus"]
PRMS_BASE_MONTHS = [dt.datetime(2022 + (9 + i) // 12, (9 + i) % 12 + 1, 1) for i in range(12)]
assert PRMS_BASE_MONTHS[0] == dt.datetime(2022, 10, 1) and PRMS_BASE_MONTHS[-1] == dt.datetime(2023, 9, 1)


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# ---------- PIPR ----------
wb = openpyxl.load_workbook(PIPR_PATH, read_only=True, data_only=True)
it = wb["Table 1"].iter_rows(values_only=True)
next(it); next(it)
hdr = list(next(it))
col = {h: i for i, h in enumerate(hdr)}
PIPR_PRICE_COLS = {"all": "Rental price", "1bed": "Rental price one bed", "2bed": "Rental price two bed",
                   "3bed": "Rental price three bed", "4plus": "Rental price four or more bed"}
pipr = {}  # code -> {date: row}
for r in it:
    if r[0] is None or r[1] not in BOROUGHS and r[1] != LONDON:
        continue
    pipr.setdefault(r[1], {})[r[0]] = r
latest = max(pipr[LONDON])
assert latest == dt.datetime(2026, 10, 1), latest


def pipr_index(code, d, name="Index"):
    return num(pipr[code][d][col[name]])


# ---------- PRMS ----------
x = xlrd.open_workbook(PRMS_PATH)
PRMS_SHEETS = {"room": "Table2.1", "studio": "Table2.2", "1bed": "Table2.3", "2bed": "Table2.4",
               "3bed": "Table2.5", "4plus": "Table2.6", "all": "Table2.7"}
prms = {}  # type -> code -> dict(count, median)
for t, sn in PRMS_SHEETS.items():
    sh = x.sheet_by_name(sn)
    assert sh.row_values(6)[7] == "Median" and sh.row_values(6)[4] == "Count of rents", sh.row_values(6)
    for i in range(7, sh.nrows):
        r = sh.row_values(i)
        if r[2] in BOROUGHS or r[2] == LONDON:
            prms.setdefault(t, {})[r[2]] = {"count": r[4], "median": num(r[7]), "raw": r[7]}

# ---------- New median/quartile dataset (comparison only) ----------
wm = openpyxl.load_workbook(MEDQ_PATH, read_only=True, data_only=True)
it = wm["Table 1"].iter_rows(values_only=True)
next(it); next(it)
mh = list(next(it))
mcol = {h.strip(): i for i, h in enumerate(mh)}
MEDQ_COLS = {"studio": ("Count of rents Studio", "Median Studio (£)"),
             "1bed": ("Count of rents One Bedrooms", "Median One Bedrooms (£)"),
             "2bed": ("Count of rents Two Bedrooms", "Median Two Bedrooms (£)"),
             "3bed": ("Count of rents Three Bedrooms", "Median Three Bedrooms (£)"),
             "4plus": ("Count of Four or more Bedrooms", "Median Four or more bedrooms (£)"),
             "all": ("Count of All categories", "All Median (£)")}
medq_rows = [r for r in it if r[0] is not None]
medq_latest = max(r[0] for r in medq_rows)
medq = {r[1]: r for r in medq_rows if r[0] == medq_latest and r[1] in BOROUGHS}

# ---------- Build ----------
def build(code):
    out, info = {}, {}
    have_pipr = code in pipr
    factor = None
    if have_pipr:
        base = [pipr_index(code, d) for d in PRMS_BASE_MONTHS]
        assert all(b is not None for b in base), (code, base)
        factor = pipr_index(code, latest) / statistics.mean(base)
        info["factor"] = factor
        info["factor_1bed_index"] = pipr_index(code, latest, "Index one bed") / statistics.mean(
            [pipr_index(code, d, "Index one bed") for d in PRMS_BASE_MONTHS])
    for t in ["room", "studio"]:
        p = prms[t][code]
        info[f"prms_{t}"] = p
        out[t] = round(p["median"] * factor) if (factor and p["median"] is not None) else None
    for t, c in PIPR_PRICE_COLS.items():
        v = num(pipr[code][latest][col[c]]) if have_pipr else None
        out[t] = round(v) if v is not None else None
    return {k: out[k] for k in TYPES + ["all"]}, info


boroughs, infos = {}, {}
for code, name in sorted(BOROUGHS.items(), key=lambda kv: kv[1]):
    boroughs[name], infos[name] = build(code)
london, london_info = build(LONDON)
assert len(boroughs) == 33

nulls = [(n, t) for n, row in boroughs.items() for t, v in row.items() if v is None]
null_by_type = {}
for n, t in nulls:
    null_by_type.setdefault(t, []).append(n)

result = {
    "title": "ONS private rents by London borough and property type",
    "units": "GBP per calendar month",
    "retrieved": "2026-11-20",
    "period_label": "October 2026",
    "property_types": TYPES,
    "type_basis": {
        "room": "ONS Private Rental Market Statistics (PRMS, VOA data) median for 'Room', tenancies active 1 Oct 2022-30 Sep 2023, uplifted to October 2026 by each borough's PIPR all-properties index change (Oct 2026 / mean Oct 2022-Sep 2023)",
        "studio": "ONS PRMS median for 'Studio', tenancies active 1 Oct 2022-30 Sep 2023, uplifted to October 2026 by each borough's PIPR all-properties index change (Oct 2026 / mean Oct 2022-Sep 2023)",
        "1bed": "ONS Price Index of Private Rents (PIPR) average rental price, one bedroom, October 2026 (released 18 Nov 2026; model-based geometric-mean price level)",
        "2bed": "ONS PIPR average rental price, two bedrooms, October 2026 (released 18 Nov 2026)",
        "3bed": "ONS PIPR average rental price, three bedrooms, October 2026 (released 18 Nov 2026)",
        "4plus": "ONS PIPR average rental price, four or more bedrooms, October 2026 (released 18 Nov 2026)",
        "all": "ONS PIPR average rental price, all property types, October 2026 (released 18 Nov 2026)",
    },
    "sources": [
        {"name": "ONS Price Index of Private Rents, UK: monthly price statistics (18 November 2026 edition), Table 1",
         "url": "https://www.ons.gov.uk/file?uri=/economy/inflationandpriceindices/datasets/priceindexofprivaterentsukmonthlypricestatistics/18november2026/priceindexofprivaterentsukmonthlypricestatistics10.xlsx",
         "release_date": "2026-11-18", "period": "October 2026 (rent levels); Oct 2022-Oct 2026 indices used for uplift",
         "statistic": "mean"},
        {"name": "ONS Private rental market summary statistics in England, October 2022 to September 2023 (final edition), Tables 2.1 (Room) and 2.2 (Studio)",
         "url": "https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/housing/datasets/privaterentalmarketsummarystatisticsinengland/october2022toseptember2023/privaterentalmarketstatistics231220.xls",
         "release_date": "2023-12-20", "period": "1 October 2022 to 30 September 2023",
         "statistic": "median"},
    ],
    "boroughs": boroughs,
    "london": london,
    "notes": [
        "PIPR figures (1bed-4plus, all) are ONS model-based average rents (geometric mean of hedonic-model prices for a fixed January 2023 basket, uprated by the index). They cover the stock of all current private tenancies (new and existing lets), not just new lets or advertised asking rents, so they will usually sit below current asking rents on listing sites.",
        "Room and studio figures are medians from ONS/VOA PRMS for tenancies active Oct 2022-Sep 2023, uplifted to October 2026 by the borough's PIPR all-properties index: factor = PIPR index Oct 2026 / mean PIPR index Oct 2022-Sep 2023. London factor %.4f; borough factors range %.4f-%.4f (per-borough factors in SOURCES.md). PIPR excludes rooms in HMOs and has no studio category, so the all-properties index is a proxy for room/studio rent growth." % (
            london_info["factor"], min(i["factor"] for i in infos.values() if "factor" in i),
            max(i["factor"] for i in infos.values() if "factor" in i)),
        "Room/studio columns are medians while 1bed-4plus/all are PIPR averages, and they come from different data processing; treat cross-column comparisons (e.g. studio vs 1bed) with care.",
        "City of London: ONS does not publish PIPR estimates for the City of London (low collection volumes), so all its cells are null. PRMS did publish City studio/1-bed figures for 2022-23 (see SOURCES.md) but there is no City index to uplift them; the app could fall back to Westminster or the London row.",
        "Room nulls: %s. PRMS had zero room records in City of London, Hammersmith and Fulham and Richmond upon Thames, and suppressed the room median (fewer than 5 records) in Bexley, Lambeth and Sutton." % ", ".join(sorted(null_by_type.get("room", []))),
        "Low-reliability room medians (PRMS count rounded to 10 records, i.e. roughly 5-14 tenancies): %s. Studio medians based on ~10 records: %s." % (
            ", ".join(sorted(n for n, i in infos.items() if i["prms_room"]["median"] is not None and num(i["prms_room"]["count"]) is not None and i["prms_room"]["count"] <= 10)),
            ", ".join(sorted(n for n, i in infos.items() if i["prms_studio"]["median"] is not None and num(i["prms_studio"]["count"]) is not None and i["prms_studio"]["count"] <= 10))),
        "ONS advises that local-authority PIPR price levels can be volatile month to month because of low collection volumes; London-wide figures are more robust.",
        "On 18 November 2026 ONS launched a new 'Private rent price median and quartiles, England and Wales' dataset (latest month September 2026, includes studios, no rooms, no London region row, City of London not published). It was not used for the main table; see SOURCES.md for the reasoning and a comparison.",
        "Values rounded to whole pounds. PIPR is not seasonally adjusted.",
    ],
}

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
    f.write("\n")

# ---------- Appendix markdown for SOURCES.md ----------
L = []
L.append("| Borough | PIPR index Oct 2026 | Mean index Oct22-Sep23 | Uplift factor (all-props) | Alt. factor (1-bed index) | PRMS room median (count) | Room out | PRMS studio median (count) | Studio out |")
L.append("|---|---|---|---|---|---|---|---|---|")
for name in list(boroughs) + ["London"]:
    code = LONDON if name == "London" else next(c for c, n in BOROUGHS.items() if n == name)
    info = london_info if name == "London" else infos[name]
    row = london if name == "London" else boroughs[name]
    if "factor" in info:
        idx_now = pipr_index(code, latest)
        idx_base = statistics.mean(pipr_index(code, d) for d in PRMS_BASE_MONTHS)
        a, b, c, d = f"{idx_now:.2f}", f"{idx_base:.2f}", f"{info['factor']:.4f}", f"{info['factor_1bed_index']:.4f}"
    else:
        a = b = c = d = "n/a (not in PIPR)"
    pr, ps = info["prms_room"], info["prms_studio"]
    L.append(f"| {name} | {a} | {b} | {c} | {d} | {pr['raw']} ({pr['count']}) | {row['room']} | {ps['raw']} ({ps['count']}) | {row['studio']} |")
L.append("")
L.append(f"New ONS median/quartiles dataset, {medq_latest:%B %Y} medians (comparison only, not used):")
L.append("")
L.append("| Borough | Studio median (count) | Our studio | 1-bed median | PIPR 1-bed | 2-bed median | PIPR 2-bed | All median | PIPR all |")
L.append("|---|---|---|---|---|---|---|---|---|")
for name, row in boroughs.items():
    code = next(c for c, n in BOROUGHS.items() if n == name)
    m = medq.get(code)
    if m is None:
        L.append(f"| {name} | not published | {row['studio']} | - | {row['1bed']} | - | {row['2bed']} | - | {row['all']} |")
        continue
    g = lambda t: m[mcol[MEDQ_COLS[t][1]]]
    fmt = lambda v: str(round(v)) if num(v) is not None else str(v)
    L.append(f"| {name} | {fmt(g('studio'))} ({m[mcol[MEDQ_COLS['studio'][0]]]}) | {row['studio']} | {fmt(g('1bed'))} | {row['1bed']} | {fmt(g('2bed'))} | {row['2bed']} | {fmt(g('all'))} | {row['all']} |")
L.append("")
L.append("PRMS 2022-23 raw medians for City of London (not used): " + ", ".join(
    f"{t} {prms[t]['E09000001']['raw']} (count {prms[t]['E09000001']['count']})" for t in PRMS_SHEETS))
with open(OUT_MD, "w", encoding="utf-8") as f:
    f.write("\n".join(L) + "\n")

print("latest PIPR month", latest.date(), "medq latest", medq_latest.date())
print("London", london, "factor", round(london_info["factor"], 4))
for n in ["Hammersmith and Fulham", "Kensington and Chelsea", "Barking and Dagenham"]:
    print(n, boroughs[n], round(infos[n]["factor"], 4))
print("nulls", null_by_type)
