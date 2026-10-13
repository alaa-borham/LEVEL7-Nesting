# GRAFIS releases — watch log

Baseline for the weekly GRAFIS update check. The check reports new GRAFIS releases and what they could mean for
LEVEL7 (file reading, marker files, DXF/AAMA/PLT/ISO export); nothing is changed in LEVEL7 until the owner
approves. Add a line here once a release has been reviewed.

## Known releases (from public release notes / press, as of 2026-10-13)
| Version / release | Date | Relevant for LEVEL7 |
|---|---|---|
| GRAFIS 23 | 07/2023 | universal tools (construction); no file-format note |
| GRAFIS 24 | 2024 | revised upper constructions |
| GRAFIS 25.0 (rental licences only) | 2025 | new interface, VStitcher plugin |
| GRAFIS 25.0 Release 38 | 2025-11-07 | first GRAFIS CAD Shoes release |
| GRAFIS 25.0 Release 39 | 2025-12-01 | smaller construction changes |
| GRAFIS 25.0 Release 40 | 2026-03-16 | no DXF/cutter entries seen |
| GRAFIS 26.0 Release 43 | 2026-08-01 | marker making: "Marker-Mini" text field, Autonester transfer fixes |
| GRAFIS 26.0 Release 43/B | 2026-09-14 | CutDataDXF export configurations stored for all users; Autonester "Temp-Targeting" |

## File variants seen in real files (signature "GRAFIS-Modelldatei" + 2 letters; #VERSION is 1000 in all)
| Variant | Files | Differences handled |
|---|---|---|
| VB, VD | Neay blue pants MDL / SCB (1430, 1500) | reference format |
| VA | vest2027-M1 MDL / OUT vest2027-M1-M SCB (created 13.10.2026, probably GRAFIS 26) | '>' piece flag, model path V="…" after the ID, alphabetical size table without references, base entry by "__" name |

Sources: grafis.com/release-notes, grafis.de/new, grafis.de/faq, fashionteamlt.fi (GRAFIS CAD 25), texprocess exhibitor page.
