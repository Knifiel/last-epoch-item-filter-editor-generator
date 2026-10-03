import struct

import pytest

from lefilter import odin


def s(text: str, wide: bool = True) -> bytes:
    return bytes([1 if wide else 0]) + struct.pack("<i", len(text)) + text.encode("utf-16-le" if wide else "latin-1")


def matrix_node(name: bytes, node_id: int, type_entry: bytes, rows: list[list[int]]) -> bytes:
    """A named int[,] reference node as MultiDimensionalArrayFormatter writes it."""
    values = b"".join(b"\x18" + struct.pack("<i", v) for row in rows for v in row)   # 24 = UnnamedInt
    return (b"\x01" + name + type_entry + struct.pack("<i", node_id)
            + b"\x06" + struct.pack("<q", len(rows) * len(rows[0]))
            + b"\x27" + s("ranks") + s(f"{len(rows)}|{len(rows[0])}") + values   # 39 = NamedString
            + b"\x07" + b"\x05")


def test_reads_nodes_arrays_and_int_matrices():
    int2d = b"\x2f" + struct.pack("<i", 1) + s("System.Int32[,], mscorlib")       # 47 = TypeName
    stream = (b"\x01" + s("data") + b"\x2f" + struct.pack("<i", 0) + s("List`1[[Grid, LE]], mscorlib") + struct.pack("<i", 0)
              + b"\x06" + struct.pack("<q", 2)
              + b"\x02" + b"\x2f" + struct.pack("<i", 2) + s("Grid, LE") + struct.pack("<i", 1)   # unnamed ref node
              + matrix_node(s("unlockMatrix"), 2, int2d, [[99, 1, 2], [3, 104, 99]]) + b"\x05"
              + b"\x02" + b"\x30" + struct.pack("<i", 2) + struct.pack("<i", 3)                 # 48 = TypeID
              + matrix_node(s("unlockMatrix"), 4, b"\x30" + struct.pack("<i", 1), [[1, 1], [1, 1]]) + b"\x05"
              + b"\x07" + b"\x05" + b"\x31")                                                       # 49 = end of stream
    top = odin.read(stream)
    data = top.get("data")
    assert data.type == "List`1[[Grid, LE]], mscorlib"
    grids = [node for _, node in data[0][1]]
    assert grids[0].type == "Grid, LE" and grids[1].type == "Grid, LE"
    assert odin.int_matrix(grids[0].get("unlockMatrix")) == [[99, 1, 2], [3, 104, 99]]
    assert odin.int_matrix(grids[1].get("unlockMatrix")) == [[1, 1], [1, 1]]


def test_rejects_truncated_or_unknown_data():
    with pytest.raises(odin.OdinError):
        odin.read(b"\x01" + s("data"))                  # a node without its type
    with pytest.raises(odin.OdinError):
        odin.read(b"\x63")                              # no such entry type
    with pytest.raises(odin.OdinError):
        odin.int_matrix(odin.Entries([("ranks", "2|2"), (None, 1)]))


def test_rejects_bad_primitive_array_lengths():
    for n, size in ((-1, 4), (2, -4), (1000, 4)):
        with pytest.raises(odin.OdinError):
            odin.read(b"\x08" + struct.pack("<ii", n, size) + b"\x00" * 8)   # 8 = PrimitiveArray
