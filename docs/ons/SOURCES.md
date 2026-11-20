# Rent Check: ONS data provenance

Built 2026-11-20 by `build_ons_table.py` (in this folder). Output: `ons_london_rents.json`.
Everything came from live downloads from ons.gov.uk (plain `curl -L -A "Mozilla/5.0"`). All downloads worked.

## Files downloaded

| # | Dataset | File URL | Release date | Period | Used for |
|---|---|---|---|---|---|
| 1 | Price Index of Private Rents (PIPR), UK: monthly price statistics, 18 November 2026 edition (sheet `Table 1`, columns `Rental price`, `Rental price one bed` / `two bed` / `three bed` / `four or more bed`, `Index`, `Index one bed`) | https://www.ons.gov.uk/file?uri=/economy/inflationandpriceindices/datasets/priceindexofprivaterentsukmonthlypricestatistics/18november2026/priceindexofprivaterentsukmonthlypricestatistics10.xlsx (dataset page: https://www.ons.gov.uk/economy/inflationandpriceindices/datasets/priceindexofprivaterentsukmonthlypricestatistics) | 18 Nov 2026 (next: 16 Dec 2026) | Jan 2015 to Oct 2026 | 1bed, 2bed, 3bed, 4plus, all (Oct 2026); index for the room/studio uplift |
| 2 | Private rental market summary statistics in England (PRMS), October 2022 to September 2023 edition, the last one (sheets `Table2.1` Room and `Table2.2` Studio, column `Median`; `Table2.3`-`Table2.7` read for City of London reference only) | https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/housing/datasets/privaterentalmarketsummarystatisticsinengland/october2022toseptember2023/privaterentalmarketstatistics231220.xls (dataset page: https://www.ons.gov.uk/peoplepopulationandcommunity/housing/datasets/privaterentalmarketsummarystatisticsinengland) | 20 Dec 2023 (discontinued) | Tenancies active 1 Oct 2022 to 30 Sep 2023 | room, studio (before uplift) |
| 3 | Private rent price median and quartiles, England and Wales, first edition (sheet `Table 1`) | https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/housing/datasets/privaterentpricemedianandquartilesenglandandwales/current/privaterentpricemedianandquartilesenglandandwales.xlsx (dataset page: https://www.ons.gov.uk/peoplepopulationandcommunity/housing/datasets/privaterentpricemedianandquartilesenglandandwales) | 18 Nov 2026 | Monthly, Oct 2025 to Sep 2026 | Comparison only (see below) |

Pages read for context: the bulletin "Private rent and house prices, UK: November 2026" (https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/privaterentandhousepricesuk/november2026) and the PIPR QMI (https://www.ons.gov.uk/peoplepopulationandcommunity/housing/methodologies/priceindexofprivaterentsqmi, last revised 20 May 2026).
What failed: only a guessed QMI URL under `/economy/.../methodologies/` (404); the correct URL above worked. No data source failed.

Raw downloads were kept in a temporary folder outside the project (`pipr_18nov2026/pipr.xlsx`, `prms_oct22sep23/prms.xls`, `medq_18nov2026/medq.xlsx`). That folder is temporary, so download again from the URLs above if you need the files.

To rebuild: `python3 -I build_ons_table.py <pipr.xlsx> <prms.xls> <medq.xlsx> <out.json> <appendix.md>` (needs `openpyxl` and `xlrd`).

## Method

- **1bed, 2bed, 3bed, 4plus, all**: PIPR "Rental price" columns for **October 2026**, for each borough (`E09`) and for London (`E12000007`), rounded to whole pounds (ONS already rounds to £1). PIPR price levels come from a model: the geometric mean of hedonic-model prices for a fixed January 2023 basket, moved forward by the index. They cover all current tenancies, new and existing. In the JSON `sources`, "statistic" is set to `mean`, meaning a geometric mean.
- **room, studio**: PRMS median for Oct 2022 to Sep 2023 multiplied by an uplift factor, rounded to whole pounds:
  `factor = PIPR all-properties Index (Oct 2026) / mean of the 12 monthly PIPR all-properties Index values for Oct 2022 to Sep 2023`.
  Each borough uses its own index, and the London row uses the London region index. The 12-month base average matches the PRMS window. I used the all-properties index because PIPR excludes HMO rooms and has no studio category. The 1-bed index would give factors 0.5 to 2.5 percentage points higher; both are shown in the table below.
- **Nulls**: City of London is null in every column, because ONS does not publish PIPR for the City (low collection volumes), so there are no 1-4+ figures and no index to uplift its PRMS figures. Room is null for Hammersmith and Fulham and Richmond upon Thames (PRMS count 0) and for Bexley, Lambeth and Sutton (PRMS suppressed the figure because it rested on fewer than 5 records). Nothing was imputed.
- The PRMS counts are rounded to the nearest 10. A count of "10" means about 5 to 14 records, so those medians are not very reliable. Affected room cells: Barking and Dagenham, Bromley, Camden, Ealing, Hackney, Havering, Islington. Affected studio cells: Barking and Dagenham, Bexley, Havering, Kingston upon Thames, Merton.

## Decisions and why

1. **Period label "October 2026"**: this is the latest PIPR month, from the 18 Nov 2026 release. Room and studio are uplifted to the same month.
2. **I found a new ONS dataset but did not use it for the main table.** On 18 Nov 2026 ONS launched "Private rent price median and quartiles, England and Wales", which replaces PRMS and has studio and 1-4+ bed medians and quartiles by local authority. I kept to the brief (PIPR for 1-4+/all, uplifted PRMS for room/studio) for three reasons:
   - It has **no London region row**, and the JSON needs a London figure. A median cannot be built from borough medians.
   - Its latest month is **September 2026**, one month behind PIPR.
   - Its studio medians look **compressed towards 1-bed levels**: about 88% to slightly over 100% of the 1-bed median, against about 60-90% (often about 70%) in PRMS. ONS derives these figures from PIPR **model-predicted** rents, not actual rents, and PIPR has no studio category, so I suspect the model prices studios close to 1-beds. If so, using these figures would make overpriced studios look fair.
   - Its 1-bed and 2-bed medians are within a few percent of the PIPR figures, which supports using PIPR for those columns.
   - Its "all" median is well below PIPR "all" in inner boroughs (for example Kensington and Chelsea £3,101 against £3,765).
   - It does have quartiles, which a "fair rent" check could use well. Worth revisiting if the app's data shape gains quartiles. The full comparison is below.
3. **Mixed statistics**: room and studio are medians of actual rents; the other columns are PIPR model-based geometric means. The geometric mean of a rent distribution is usually close to its median, and the new ONS median data confirms this for 1-2 bed. Even so, the app should not present the studio/1-bed gap as exact.
4. **Coverage**: ONS rent figures cover all current tenancies, existing ones included. New-let and asking rents on Rightmove or Zoopla run noticeably higher, especially in London where rents have risen fast. The app should say "compared with typical rents paid by current tenants (ONS)", not "market asking rent".
5. **City of London**: left null, not filled from Westminster or London, because the brief said never invent numbers. PRMS 2022-23 raw medians for the City are listed at the end for reference.

## Uplift factors and room/studio inputs per borough

| Borough | PIPR index Oct 2026 | Mean index Oct22-Sep23 | Uplift factor (all-props) | Alt. factor (1-bed index) | PRMS room median (count) | Room out | PRMS studio median (count) | Studio out |
|---|---|---|---|---|---|---|---|---|
| Barking and Dagenham | 130.95 | 101.14 | 1.2948 | 1.3006 | 600.0 (10.0) | 777 | 750.0 (10.0) | 971 |
| Barnet | 125.33 | 102.18 | 1.2266 | 1.2431 | 650.0 (30.0) | 797 | 1000.0 (110.0) | 1227 |
| Bexley | 127.13 | 101.14 | 1.2570 | 1.2700 | .. (-) | None | 950.0 (10.0) | 1194 |
| Brent | 133.75 | 101.84 | 1.3134 | 1.3231 | 810.0 (40.0) | 1064 | 875.0 (30.0) | 1149 |
| Bromley | 122.63 | 101.25 | 1.2112 | 1.2263 | 675.0 (10.0) | 818 | 900.0 (40.0) | 1090 |
| Camden | 127.17 | 102.82 | 1.2369 | 1.2588 | 900.0 (10.0) | 1113 | 1045.0 (190.0) | 1293 |
| City of London | n/a (not in PIPR) | n/a (not in PIPR) | n/a (not in PIPR) | n/a (not in PIPR) | . (0.0) | None | 1950.0 (30.0) | None |
| Croydon | 127.72 | 101.59 | 1.2573 | 1.2656 | 617.0 (50.0) | 776 | 1000.0 (210.0) | 1257 |
| Ealing | 132.55 | 101.51 | 1.3057 | 1.3224 | 796.0 (10.0) | 1039 | 1088.0 (60.0) | 1421 |
| Enfield | 130.63 | 101.19 | 1.2910 | 1.3093 | 700.0 (20.0) | 904 | 950.0 (30.0) | 1226 |
| Greenwich | 132.08 | 101.44 | 1.3020 | 1.3155 | 733.0 (50.0) | 954 | 988.0 (20.0) | 1286 |
| Hackney | 132.20 | 101.68 | 1.3001 | 1.3164 | 700.0 (10.0) | 910 | 1300.0 (40.0) | 1690 |
| Hammersmith and Fulham | 131.06 | 102.34 | 1.2807 | 1.3040 | . (0.0) | None | 1092.0 (70.0) | 1399 |
| Haringey | 127.87 | 101.31 | 1.2622 | 1.2799 | 856.0 (30.0) | 1080 | 975.0 (90.0) | 1231 |
| Harrow | 125.81 | 101.07 | 1.2448 | 1.2554 | 695.0 (20.0) | 865 | 888.0 (30.0) | 1105 |
| Havering | 128.55 | 101.61 | 1.2651 | 1.2797 | 700.0 (10.0) | 886 | 800.0 (10.0) | 1012 |
| Hillingdon | 128.13 | 101.30 | 1.2649 | 1.2760 | 673.0 (20.0) | 851 | 900.0 (60.0) | 1138 |
| Hounslow | 134.40 | 102.22 | 1.3148 | 1.3255 | 675.0 (100.0) | 888 | 1000.0 (110.0) | 1315 |
| Islington | 137.61 | 102.16 | 1.3470 | 1.3731 | 777.0 (10.0) | 1047 | 1150.0 (50.0) | 1549 |
| Kensington and Chelsea | 128.24 | 103.21 | 1.2425 | 1.2687 | 910.0 (40.0) | 1131 | 1517.0 (390.0) | 1885 |
| Kingston upon Thames | 122.27 | 101.77 | 1.2015 | 1.2152 | 650.0 (20.0) | 781 | 998.0 (10.0) | 1199 |
| Lambeth | 130.98 | 101.48 | 1.2908 | 1.3088 | .. (-) | None | 950.0 (80.0) | 1226 |
| Lewisham | 124.56 | 101.43 | 1.2281 | 1.2404 | 750.0 (100.0) | 921 | 1000.0 (80.0) | 1228 |
| Merton | 124.79 | 100.97 | 1.2359 | 1.2502 | 750.0 (40.0) | 927 | 1050.0 (10.0) | 1298 |
| Newham | 125.93 | 101.49 | 1.2409 | 1.2488 | 780.0 (50.0) | 968 | 1100.0 (30.0) | 1365 |
| Redbridge | 128.12 | 101.61 | 1.2609 | 1.2773 | 748.0 (40.0) | 943 | 900.0 (40.0) | 1135 |
| Richmond upon Thames | 130.63 | 100.90 | 1.2947 | 1.3137 | . (0.0) | None | 1040.0 (30.0) | 1346 |
| Southwark | 128.14 | 102.25 | 1.2533 | 1.2714 | 850.0 (30.0) | 1065 | 1150.0 (40.0) | 1441 |
| Sutton | 128.43 | 101.96 | 1.2596 | 1.2727 | .. (-) | None | 800.0 (60.0) | 1008 |
| Tower Hamlets | 130.38 | 103.11 | 1.2646 | 1.2736 | 845.0 (30.0) | 1069 | 1525.0 (80.0) | 1928 |
| Waltham Forest | 124.44 | 101.39 | 1.2273 | 1.2408 | 633.0 (30.0) | 777 | 988.0 (40.0) | 1213 |
| Wandsworth | 126.01 | 100.98 | 1.2478 | 1.2701 | 773.0 (50.0) | 965 | 1113.0 (50.0) | 1389 |
| Westminster | 126.51 | 104.93 | 1.2056 | 1.2257 | 945.0 (20.0) | 1139 | 1440.0 (180.0) | 1736 |
| London | 128.39 | 102.21 | 1.2562 | 1.2726 | 750.0 (870.0) | 942 | 1100.0 (2290.0) | 1382 |

New ONS median/quartiles dataset, September 2026 medians (comparison only, not used):

| Borough | Studio median (count) | Our studio | 1-bed median | PIPR 1-bed | 2-bed median | PIPR 2-bed | All median | PIPR all |
|---|---|---|---|---|---|---|---|---|
| Barking and Dagenham | 1189 ([c]) | 971 | 1321 | 1380 | 1634 | 1727 | 1649 | 1704 |
| Barnet | 1340 (120) | 1227 | 1474 | 1506 | 1837 | 1868 | 1816 | 1959 |
| Bexley | 1106 (23) | 1194 | 1219 | 1235 | 1543 | 1535 | 1630 | 1546 |
| Brent | 1615 (153) | 1149 | 1670 | 1579 | 2064 | 1940 | 1977 | 2022 |
| Bromley | 1158 (23) | 1090 | 1301 | 1328 | 1636 | 1662 | 1624 | 1706 |
| Camden | 1920 (258) | 1293 | 2033 | 2069 | 2630 | 2644 | 2418 | 2844 |
| City of London | not published | None | - | None | - | None | - | None |
| Croydon | 1155 (40) | 1257 | 1256 | 1273 | 1579 | 1585 | 1557 | 1594 |
| Ealing | 1518 (64) | 1421 | 1650 | 1644 | 2022 | 2053 | 1957 | 2131 |
| Enfield | 1291 (24) | 1226 | 1373 | 1429 | 1738 | 1774 | 1771 | 1837 |
| Greenwich | 1635 (65) | 1286 | 1626 | 1568 | 1991 | 1941 | 1936 | 2003 |
| Hackney | 1657 (43) | 1690 | 1994 | 2015 | 2494 | 2510 | 2359 | 2680 |
| Hammersmith and Fulham | 1952 (101) | 1399 | 2014 | 2037 | 2546 | 2673 | 2438 | 2880 |
| Haringey | 1523 (79) | 1231 | 1629 | 1651 | 2035 | 2052 | 1979 | 2238 |
| Harrow | 1344 (69) | 1105 | 1341 | 1395 | 1712 | 1720 | 1781 | 1784 |
| Havering | 1156 ([c]) | 1012 | 1212 | 1221 | 1515 | 1548 | 1587 | 1571 |
| Hillingdon | 1287 (67) | 1138 | 1257 | 1270 | 1619 | 1611 | 1625 | 1594 |
| Hounslow | 1361 (19) | 1315 | 1605 | 1593 | 1967 | 1963 | 1953 | 1970 |
| Islington | 1940 (53) | 1549 | 2178 | 2196 | 2757 | 2722 | 2555 | 2894 |
| Kensington and Chelsea | 2418 (277) | 1885 | 2733 | 2691 | 3509 | 3500 | 3101 | 3765 |
| Kingston upon Thames | 1308 ([c]) | 1199 | 1393 | 1394 | 1743 | 1776 | 1720 | 1832 |
| Lambeth | 1698 (86) | 1226 | 1901 | 1905 | 2317 | 2372 | 2253 | 2559 |
| Lewisham | 1321 (153) | 1228 | 1429 | 1462 | 1795 | 1798 | 1715 | 1838 |
| Merton | 1487 (34) | 1298 | 1628 | 1653 | 1997 | 2043 | 2032 | 2192 |
| Newham | 1402 (118) | 1365 | 1610 | 1639 | 1899 | 2006 | 1865 | 1940 |
| Redbridge | 1283 (29) | 1135 | 1356 | 1381 | 1722 | 1699 | 1731 | 1744 |
| Richmond upon Thames | 1701 (31) | 1346 | 1778 | 1755 | 2238 | 2254 | 2278 | 2367 |
| Southwark | 1811 (32) | 1441 | 1994 | 1923 | 2451 | 2409 | 2317 | 2538 |
| Sutton | 1173 (31) | 1008 | 1246 | 1256 | 1549 | 1579 | 1516 | 1580 |
| Tower Hamlets | 1964 (93) | 1928 | 2002 | 2005 | 2454 | 2436 | 2261 | 2472 |
| Waltham Forest | 1293 (40) | 1213 | 1380 | 1421 | 1679 | 1750 | 1650 | 1791 |
| Wandsworth | 1745 (91) | 1389 | 1944 | 1950 | 2441 | 2479 | 2410 | 2651 |
| Westminster | 2306 (247) | 1736 | 2518 | 2563 | 3230 | 3330 | 2944 | 3217 |

PRMS 2022-23 raw medians for City of London (not used): room . (count 0.0), studio 1950.0 (count 30.0), 1bed 2058.0 (count 60.0), 2bed 2700.0 (count 20.0), 3bed .. (count -), 4plus . (count 0.0), all 2159.0 (count 110.0)
