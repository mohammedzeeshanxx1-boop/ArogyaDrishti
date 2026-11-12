#!/usr/bin/env python3
"""Remove type-use annotation attributes from selected class files inside a jar (no JDK needed).

Why: Hibernate's bundled Jandex in the HAPI FHIR 5.7.0 CLI crashes (ArrayIndexOutOfBoundsException)
on 10 Guava classes that carry Checker Framework type-use annotations, so `run-server` cannot start.
RuntimeVisibleTypeAnnotations / RuntimeInvisibleTypeAnnotations are metadata only; this tool drops
just those attributes (class, field, method and Code level) and copies everything else byte-for-byte.

Usage: strip_type_annotations.py <jar> <list-of-class-entries> <output-dir>
Writes the patched .class files under <output-dir> using their jar paths.
"""

from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

DROP = {b"RuntimeVisibleTypeAnnotations", b"RuntimeInvisibleTypeAnnotations"}
CP_SIZES = {3: 4, 4: 4, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4, 15: 3, 16: 2, 17: 4, 18: 4, 19: 2, 20: 2}


class Reader:
    def __init__(self, data: bytes):
        self.d, self.p = data, 0

    def take(self, n: int) -> bytes:
        b = self.d[self.p:self.p + n]
        if len(b) != n:
            raise ValueError("truncated class file")
        self.p += n
        return b

    def u2(self) -> int:
        return struct.unpack(">H", self.take(2))[0]

    def u4(self) -> int:
        return struct.unpack(">I", self.take(4))[0]


def strip(data: bytes) -> tuple[bytes, int]:
    r = Reader(data)
    out = bytearray(r.take(8))                      # magic, minor, major
    count = r.u2()
    out += struct.pack(">H", count)
    utf8: dict[int, bytes] = {}
    i = 1
    while i < count:
        tag = r.take(1)[0]
        out.append(tag)
        if tag == 1:
            n = r.u2()
            s = r.take(n)
            utf8[i] = s
            out += struct.pack(">H", n) + s
        elif tag in (5, 6):
            out += r.take(8)
            i += 1                                  # long/double use two slots
        elif tag in CP_SIZES:
            out += r.take(CP_SIZES[tag])
        else:
            raise ValueError(f"unknown constant pool tag {tag}")
        i += 1
    removed = 0

    def attributes() -> bytes:
        nonlocal removed
        n = r.u2()
        kept = []
        for _ in range(n):
            name = r.u2()
            length = r.u4()
            body = r.take(length)
            key = utf8.get(name)
            if key in DROP:
                removed += 1
                continue
            if key == b"Code":
                body = code(body)
            kept.append(struct.pack(">HI", name, len(body)) + body)
        return struct.pack(">H", len(kept)) + b"".join(kept)

    def code(body: bytes) -> bytes:
        nonlocal r
        outer, r = r, Reader(body)
        head = r.take(4)                            # max_stack, max_locals
        clen = r.u4()
        c = r.take(clen)
        ex = r.u2()
        ext = r.take(8 * ex)
        attrs = attributes()
        r = outer
        return head + struct.pack(">I", clen) + c + struct.pack(">H", ex) + ext + attrs

    out += r.take(6)                                # access, this, super
    ni = r.u2()
    out += struct.pack(">H", ni) + r.take(2 * ni)
    for _ in range(2):                              # fields, then methods
        n = r.u2()
        out += struct.pack(">H", n)
        for _ in range(n):
            out += r.take(6)
            out += attributes()
    out += attributes()
    if r.p != len(data):
        raise ValueError("trailing bytes after class file")
    return bytes(out), removed


def main() -> None:
    jar, listing, outdir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    names = [l.strip() for l in listing.read_text().splitlines() if l.strip()]
    with zipfile.ZipFile(jar) as z:
        for name in names:
            patched, n = strip(z.read(name))
            dest = outdir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(patched)
            print(f"stripped {n} type-annotation attribute(s): {name}")


if __name__ == "__main__":
    main()
