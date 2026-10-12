"""GRAFIS binary container ("GRAFIS-ModelldateiVB") — block chain parser.

Structure established from the sample files (see docs/GRAFIS_FORMAT.md):

    offset 0   u32  unknown (varies per file; not a simple sum/CRC32/Adler32)
    offset 4   u32  (file_size - 8) / 8           -> verified on both samples
    offset 8   b"GRAFIS-ModelldateiVB\\n\\0\\n\\0" then zero padding up to offset 80
    offset 80  block chain, each block:
                   u32  unknown (per-block check value, algorithm unknown)
                   u32  block length in 8-byte units, measured from the block start
                   8s   b"BLO5kenn"
                   4*u32 hierarchical block id (a, b, c, d)
                   payload (length*8 - 32 bytes)
    end        b"mdlEND_5" (8 bytes)

Blocks are never located by searching for ``BLO5kenn``; the chain is followed
strictly through the length field and every step is validated.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

SIGNATURE = b"GRAFIS-ModelldateiVB"
BLOCK_MARK = b"BLO5kenn"
TRAILER = b"mdlEND_5"
CHAIN_START = 80


class GrafisFormatError(Exception):
    """Raised when a file is not a readable GRAFIS container."""


@dataclass
class Block:
    offset: int
    check: int
    units: int
    bid: tuple[int, int, int, int]
    payload: bytes

    @property
    def size(self) -> int:
        return self.units * 8


@dataclass
class Container:
    path: str
    size: int
    sha256: str
    header_u32: tuple[int, int]
    blocks: list[Block]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_id(self) -> dict[tuple[int, int, int, int], Block]:
        return {b.bid: b for b in self.blocks}

    def get(self, *bid: int) -> Block | None:
        for b in self.blocks:
            if b.bid == tuple(bid):
                return b
        return None

    @property
    def ok(self) -> bool:
        return not self.errors


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_container(data: bytes, path: str = "<memory>", strict: bool = False) -> Container:
    """Parse the block chain. Never raises for damaged chains unless ``strict``;
    problems are collected in ``Container.errors``."""
    if len(data) < CHAIN_START + 8 or SIGNATURE not in data[:64]:
        raise GrafisFormatError("signature GRAFIS-ModelldateiVB not found in file header")
    h0, h1 = struct.unpack_from("<II", data, 0)
    cont = Container(path=path, size=len(data), sha256=sha256_bytes(data), header_u32=(h0, h1), blocks=[])
    if h1 * 8 + 8 != len(data):
        cont.errors.append(f"header length field {h1}*8+8={h1 * 8 + 8} != file size {len(data)} (truncated or padded file)")
    end = len(data) - 8 if data[-8:] == TRAILER else len(data)
    if data[-8:] != TRAILER:
        cont.errors.append("trailer mdlEND_5 missing")
    pos = CHAIN_START
    while pos < end:
        if pos + 32 > end:
            cont.errors.append(f"truncated block header at offset {pos}")
            break
        check, units = struct.unpack_from("<II", data, pos)
        mark = data[pos + 8:pos + 16]
        if mark != BLOCK_MARK:
            cont.errors.append(f"block marker missing at offset {pos}; chain broken")
            break
        if units < 4 or pos + units * 8 > end:
            cont.errors.append(f"invalid block length {units} at offset {pos}")
            break
        bid = struct.unpack_from("<4I", data, pos + 16)
        cont.blocks.append(Block(pos, check, units, bid, bytes(data[pos + 32:pos + units * 8])))
        pos += units * 8
    if pos != end and not cont.errors:
        cont.errors.append(f"block chain ended at {pos}, expected {end}")
    if strict and cont.errors:
        raise GrafisFormatError("; ".join(cont.errors))
    return cont


def read_container(path: str, strict: bool = False) -> Container:
    with open(path, "rb") as fh:
        data = fh.read()
    return parse_container(data, path, strict)
