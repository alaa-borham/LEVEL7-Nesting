"""Text sections stored in block (2,1,0,0): #VERSION, #GRDTAB, #TLIST, #TFLIST..., #SBINFO, #SBGRLST, #SBTLIST.

Text is CRLF separated. Arabic names decode correctly as Windows-1256 on the sample
files (checked visually and by the absence of undefined code points); the encoding is
configurable because this is evidence from two files, not a format guarantee.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DEFAULT_ENCODING = "cp1256"


@dataclass
class TListEntry:
    number: int            # part number, equals block index b in (3, b, *, *)
    name: str
    flagged: bool          # "x" after the number (MDL); meaning: marked part (probable)
    production: bool       # has "x O/F 01 0n" columns -> part has production (cut) attributes
    material: str | None   # "O" / "F" from the production column
    count: int | None      # first 2-digit column (copies)  [probable]
    mirrored: int | None   # second 2-digit column (mirrored copies) [probable]
    piece_id: str          # ID=... (64-bit hex, shared between MDL and SCB)
    raw: str


@dataclass
class SizeEntry:
    index: int             # 1-based GRDTAB index = geometry block d in (3, b, 7, d)
    name: str
    ref: str | None        # "__HN40_0" etc.


@dataclass
class MeasureTable:
    part: int
    kind: str              # "TFLIST" or "BFLIST"
    rows: list[tuple[str, str, str, list[str]]]  # (code, unit, label, values per GRDTAB index)


@dataclass
class SBTListEntry:
    number: int
    name: str
    count: int
    mirrored: int
    flags: str
    rest: list[str]


@dataclass
class TextSections:
    raw: str
    sections: dict[str, list[str]] = field(default_factory=dict)
    offsets: dict[str, int] = field(default_factory=dict)
    version: str | None = None
    sizes: list[SizeEntry] = field(default_factory=list)
    tlist: list[TListEntry] = field(default_factory=list)
    measure_tables: list[MeasureTable] = field(default_factory=list)
    sbinfo: dict[str, str] = field(default_factory=dict)
    sbgrlst: list[tuple[int, str]] = field(default_factory=list)
    sbtlist: list[SBTListEntry] = field(default_factory=list)
    unparsed: dict[str, list[str]] = field(default_factory=dict)   # section -> lines in an unknown layout


_SEC = re.compile(r"^#([A-Z]+[A-Z0-9]*)\s*$")


def parse_text(payload: bytes, encoding: str = DEFAULT_ENCODING) -> TextSections:
    text = payload.rstrip(b"\x00").decode(encoding, errors="replace")
    ts = TextSections(raw=text)
    cur = None
    byte_pos = 0
    for line in text.split("\r\n"):
        m = _SEC.match(line)
        if m:
            cur = m.group(1)
            ts.sections[cur] = []
            ts.offsets[cur] = byte_pos
        elif cur is not None:
            ts.sections[cur].append(line)
        byte_pos += len(line.encode(encoding, errors="replace")) + 2
    if "VERSION" in ts.sections and ts.sections["VERSION"]:
        ts.version = ts.sections["VERSION"][0].strip()
    for line in ts.sections.get("GRDTAB", []):
        m = re.match(r"\s*>\s*(\d+)\s+(\S+)(?:\s*=>\s*(\S+))?", line)
        if m:
            ts.sizes.append(SizeEntry(int(m.group(1)), m.group(2), m.group(3)))
        elif line.strip():
            ts.unparsed.setdefault("GRDTAB", []).append(line)
    for line in ts.sections.get("TLIST", []):
        e = _parse_tlist_line(line)
        if e:
            ts.tlist.append(e)
        elif line.strip():
            ts.unparsed.setdefault("TLIST", []).append(line)
    for key, lines in ts.sections.items():
        m = re.match(r"(TFLIST|BFLIST)(\d+)$", key)
        if m:
            rows = []
            for ln in lines:
                cols = ln.split("\t")
                if not cols or cols[0].strip() == "*" or len(cols) < 5:
                    continue
                rows.append((cols[0].strip(), cols[1].strip(), cols[2].strip(), [c.strip() for c in cols[4:]]))
            ts.measure_tables.append(MeasureTable(int(m.group(2)), m.group(1), rows))
    for line in ts.sections.get("SBINFO", []):
        m = re.match(r"([A-Z]+?)(?:\s+|(?=\d))(.*)$", line)
        if m:
            ts.sbinfo[m.group(1)] = m.group(2).strip()
    for line in ts.sections.get("SBGRLST", []):
        m = re.match(r"\s*(\d+)\s+(\S+)", line)
        if m:
            ts.sbgrlst.append((int(m.group(1)), m.group(2)))
    for line in ts.sections.get("SBTLIST", []):
        m = re.match(r"(\d{3})\s(.+?)\s+(\d+)\s+(\d+)\s+(\S+)\s*(.*)$", line)
        if m:
            ts.sbtlist.append(SBTListEntry(int(m.group(1)), m.group(2).strip(), int(m.group(3)), int(m.group(4)),
                                           m.group(5), m.group(6).split()))
        elif line.strip():
            ts.unparsed.setdefault("SBTLIST", []).append(line)
    return ts


# leading flag: "*" (MDL, SCB of older GRAFIS) or ">" (SCB of newer GRAFIS); newer SCBs also append the model
# path after the ID:  ' > 014   name   1 1 O  x O 01 01 ID=0060FB8A01DD5AA1 V="A:\\vest\\vest.mdl"'
_TL = re.compile(r'^\s*([^\w\s]?)\s*(\d{3})\s(x|\s)\s(.*?)\s+ID=([0-9A-Fa-f]+)(?:\s+[A-Z]+="[^"]*")*\s*$')


def _parse_tlist_line(line: str) -> TListEntry | None:
    m = _TL.match(line)
    if not m:
        return None
    number = int(m.group(2))
    flagged = m.group(3) == "x"
    body = m.group(4)
    prod = re.search(r"\bx\s+([A-Z])\s+(\d\d)\s+(\d\d)\s*$", body)
    material = count = mirrored = None
    if prod:
        material, count, mirrored = prod.group(1), int(prod.group(2)), int(prod.group(3))
        body = body[:prod.start()]
    # MDL: "name   83 510" (the two numbers run together when wide: "basic  2381152")
    # SCB: "name   1 1 O " or "name   -"
    name = re.sub(r"\s+(-|\d+(\s+\d+)?(\s+[A-Z])?)\s*$", "", body).strip()
    return TListEntry(number, name, flagged, prod is not None, material, count, mirrored, m.group(5), line)
