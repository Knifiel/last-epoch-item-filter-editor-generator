"""Reader for Odin Serializer's binary format (Sirenix BinaryDataWriter), which the game uses for
SerializedScriptableObject fields Unity can't store itself - e.g. the int[,] cell matrices of
IdolsContainerGridDataList (idol altar layouts), found in serializationData.SerializedBytes.

Only reads: every node and array becomes an Entries list of (name, value) pairs (name None for
unnamed entries), node types are kept as Entries.type.
"""
from __future__ import annotations

import struct

# BinaryEntryType values -> (struct format of the payload, or a handler name); odd = named, even = unnamed
# for the paired kinds.
_PRIMITIVES = {15: "b", 16: "b", 17: "B", 18: "B", 19: "h", 20: "h", 21: "H", 22: "H", 23: "i", 24: "i",
               25: "I", 26: "I", 27: "q", 28: "q", 29: "Q", 30: "Q", 31: "f", 32: "f", 33: "d", 34: "d",
               43: "?", 44: "?"}
_NAMED = {1, 3, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 43, 45, 50}
START_REF, START_STRUCT, END_NODE, START_ARRAY, END_ARRAY, PRIMITIVE_ARRAY = (1, 2), (3, 4), 5, 6, 7, 8
TYPE_NAME, TYPE_ID, END_OF_STREAM = 47, 48, 49


class OdinError(ValueError):
    pass


class Entries(list):
    """A node's or array's entries: [(name, value)]; type = the node's .NET type name."""
    type: str | None = None

    def get(self, name: str, default=None):
        return next((v for n, v in self if n == name), default)

    def values(self) -> list:
        return [v for n, v in self if n is None]


class _Reader:
    def __init__(self, data: bytes):
        self.buf, self.pos, self.types = bytes(data), 0, {}

    def take(self, fmt: str):
        try:
            v = struct.unpack_from("<" + fmt, self.buf, self.pos)[0]
        except struct.error as e:
            raise OdinError(f"truncated at byte {self.pos}") from e
        self.pos += struct.calcsize(fmt)
        return v

    def string(self) -> str:
        wide, n = self.take("B"), self.take("i")
        size = n * (2 if wide else 1)
        raw = self.buf[self.pos:self.pos + size]
        if len(raw) != size:
            raise OdinError(f"truncated string at byte {self.pos}")
        self.pos += size
        return raw.decode("utf-16-le" if wide else "latin-1")

    def type_entry(self) -> str | None:
        kind = self.take("B")
        if kind == TYPE_NAME:
            tid = self.take("i")
            self.types[tid] = self.string()
            return self.types[tid]
        if kind == TYPE_ID:
            return self.types.get(self.take("i"))
        if kind in (45, 46):   # null type
            return None
        raise OdinError(f"unexpected type entry {kind} at byte {self.pos - 1}")

    def entries(self, until: int | None) -> Entries:
        out = Entries()
        while self.pos < len(self.buf):
            kind = self.take("B")
            if kind == until:
                return out
            if kind == END_OF_STREAM:
                break
            name = self.string() if kind in _NAMED else None
            if kind in START_REF or kind in START_STRUCT:
                node_type = self.type_entry()
                if kind in START_REF:
                    self.take("i")   # node id
                node = self.entries(END_NODE)
                node.type = node_type
                out.append((name, node))
            elif kind == START_ARRAY:
                self.take("q")       # length
                out.append((name, self.entries(END_ARRAY)))
            elif kind == PRIMITIVE_ARRAY:
                n, size = self.take("i"), self.take("i")
                if n < 0 or size < 0 or self.pos + n * size > len(self.buf):
                    raise OdinError(f"bad primitive array ({n} x {size} bytes) at byte {self.pos}")
                raw = self.buf[self.pos:self.pos + n * size]
                self.pos += n * size
                out.append((name, raw))
            elif kind in _PRIMITIVES:
                out.append((name, self.take(_PRIMITIVES[kind])))
            elif kind in (39, 40, 50, 51):     # string, external reference by string
                out.append((name, self.string()))
            elif kind in (9, 10, 11, 12):      # internal / external reference by index
                out.append((name, ("ref", self.take("i"))))
            elif kind in (45, 46):
                out.append((name, None))
            else:
                raise OdinError(f"unsupported entry type {kind} at byte {self.pos - 1}")
        if until is not None:
            raise OdinError("stream ended inside a node")
        return out


def read(data: bytes) -> Entries:
    """The top-level entries of an Odin binary stream."""
    return _Reader(data).entries(None)


def int_matrix(node: Entries) -> list[list[int]]:
    """An int[,] node (MultiDimensionalArrayFormatter: an array of "ranks" = "a|b" and the values,
    last index fastest) as rows m[i][j]."""
    array = node[0][1] if node and isinstance(node[0][1], Entries) else node
    ranks = [int(r) for r in str(array.get("ranks", "")).split("|") if r]
    values = array.values()
    if len(ranks) != 2 or ranks[0] * ranks[1] != len(values):
        raise OdinError(f"not a 2D int matrix (ranks {ranks}, {len(values)} values)")
    return [values[i * ranks[1]:(i + 1) * ranks[1]] for i in range(ranks[0])]
