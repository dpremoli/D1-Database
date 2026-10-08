"""A streaming MATLAB v7.3 (HDF5) .mat writer for captures too long for the v5 format (#194).

MAT v5 keeps a variable's byte size in a 32-bit field, so finalize.py cannot write one DATA array of
more than ~2 GB there. v7.3 is HDF5 and has no such cap. This module writes the same variables the
v5 file holds -- `DATA` (n x columns, double), `metadata` (a 1x1 struct) and `VariableNames` (a 1xN
cell of char) -- but appends DATA block by block, so memory stays a few blocks however long the cut.

What MATLAB's `load` / `matfile` need to see a valid v7.3 file (this is the layout MATLAB itself and
hdf5storage write; there is no MATLAB in CI, so the guard tests check each point by reading the file
back with h5py):

* a 512-byte userblock: "MATLAB 7.3 MAT-file, ..." text, then at byte 124 the version 0x0200 and the
  endian marker "IM" (little endian);
* every variable is a root-level dataset or group carrying a `MATLAB_class` attribute;
* MATLAB is column-major, HDF5 row-major, so an m x n MATLAB array is stored as an (n, m) HDF5 dataset
  (the array transposed); a 1 x n row is (n, 1) and a scalar (1, 1);
* char is uint16 UTF-16 code units, class "char", with `MATLAB_int_decode` = 2; an empty char is a
  uint64 [0, 0] dataset with `MATLAB_empty` = 1;
* a struct is a group (class "struct") whose fields are its children, with `MATLAB_fields` listing the
  field names; a cell is an (n, 1) dataset of object references into the root `#refs#` group, whose
  class is "cell".
"""

from __future__ import annotations

import os
import time
from typing import Any

import h5py
import numpy as np

USERBLOCK_BYTES = 512
_HEADER_TEXT = "MATLAB 7.3 MAT-file, Platform: force-app, Created on: {stamp} HDF5 schema 1.00 ."

# numpy dtype -> MATLAB class name. bool is written as uint8 with class "logical".
_CLASSES = {
    np.dtype("float64"): "double",
    np.dtype("float32"): "single",
    np.dtype("int8"): "int8",
    np.dtype("uint8"): "uint8",
    np.dtype("int16"): "int16",
    np.dtype("uint16"): "uint16",
    np.dtype("int32"): "int32",
    np.dtype("uint32"): "uint32",
    np.dtype("int64"): "int64",
    np.dtype("uint64"): "uint64",
}


def _chunk_rows(block_rows: int, n: int) -> int:
    """Chunk length (samples) along the time axis: a divisor-ish of the streaming block, about a
    few MB per chunk, so each block write covers whole chunks and nothing is compressed twice."""
    c = max(1, int(block_rows))
    while c > 100_000 and c % 2 == 0:
        c //= 2
    return max(1, min(c, n))


def _set_class(obj: h5py.HLObject, name: str) -> None:
    obj.attrs.create("MATLAB_class", np.bytes_(name.encode("ascii")))


def _char_codes(s: str) -> np.ndarray:
    return np.frombuffer(s.encode("utf-16-le"), dtype="<u2").astype(np.uint16)


class Mat73Writer:
    """Write to `path` (an HDF5 file with a MATLAB header). Use as a context manager, or call
    `close()`; the 512-byte header is stamped on close. A failure partway leaves a file without a
    valid header, so callers write to a temporary name and rename it only after a clean close."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._f = h5py.File(path, "w", userblock_size=USERBLOCK_BYTES)
        self._refs: h5py.Group | None = None
        self._n_refs = 0
        self._data: h5py.Dataset | None = None

    def __enter__(self) -> Mat73Writer:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # --- variables -------------------------------------------------------------------------------

    def write_variable(self, name: str, value: Any) -> None:
        self._write(self._f, name, value)

    def create_data(self, n: int, n_cols: int, block_rows: int, name: str = "DATA") -> None:
        """Create the n x n_cols double matrix, to be filled by `write_rows`. Stored as an
        (n_cols, n) dataset: the transpose of the MATLAB array, chunked along time and gzipped."""
        chunk = (n_cols, _chunk_rows(block_rows, n))
        self._data = self._f.create_dataset(
            name,
            shape=(n_cols, n),
            dtype="<f8",
            chunks=chunk,
            compression="gzip",
            compression_opts=1,
            shuffle=True,
        )
        _set_class(self._data, "double")

    def write_rows(self, start: int, block: np.ndarray) -> None:
        """DATA[start : start + len(block), :] = block (block is rows x columns, as MATLAB sees it)."""
        assert self._data is not None, "create_data first"
        self._data[:, start : start + block.shape[0]] = block.T

    def close(self) -> None:
        if self._f.id.valid:
            self._f.close()
        stamp = time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime())
        head = _HEADER_TEXT.format(stamp=stamp).encode("ascii")[:116].ljust(124, b" ")
        head += b"\x00\x02IM"  # version 0x0200, little-endian marker
        with open(self.path, "r+b") as fh:
            fh.seek(0)
            fh.write(head.ljust(USERBLOCK_BYTES, b"\x00"))

    def abort(self) -> None:
        """Close without a header and delete the file (a failed write)."""
        try:
            if self._f.id.valid:
                self._f.close()
        finally:
            try:
                os.remove(self.path)
            except OSError:
                pass

    # --- value encoding --------------------------------------------------------------------------

    def _write(self, parent: h5py.Group, name: str, value: Any) -> None:
        if isinstance(value, dict):
            self._write_struct(parent, name, value)
        elif isinstance(value, str):
            self._write_char(parent, name, value)
        elif isinstance(value, list | tuple) or (
            isinstance(value, np.ndarray) and value.dtype.kind in "OUS"
        ):
            items = list(value.ravel()) if isinstance(value, np.ndarray) else list(value)
            if all(isinstance(v, str | np.str_) for v in items):
                self._write_cell_of_char(parent, name, [str(v) for v in items])
            else:
                self._write_numeric(parent, name, np.asarray(value))
        else:
            self._write_numeric(parent, name, np.asarray(value))

    def _write_numeric(self, parent: h5py.Group, name: str, arr: np.ndarray) -> None:
        if arr.dtype == np.bool_:
            cls, arr = "logical", arr.astype(np.uint8)
        else:
            cls = _CLASSES.get(arr.dtype)
            if cls is None:
                # anything exotic (object, complex, ...): store its text rather than fail
                self._write_char(parent, name, str(arr.tolist()))
                return
        # scalar -> 1x1, 1-D -> a 1xN row, 2-D as is; HDF5 holds the transpose
        arr = arr.reshape(1, 1) if arr.ndim == 0 else (arr.reshape(1, -1) if arr.ndim == 1 else arr)
        ds = parent.create_dataset(name, data=np.ascontiguousarray(arr.T))
        _set_class(ds, cls)

    def _write_char(self, parent: h5py.Group, name: str, s: str) -> None:
        if not s:
            ds = parent.create_dataset(name, data=np.array([0, 0], dtype=np.uint64))
            ds.attrs.create("MATLAB_empty", np.uint8(1))
        else:
            ds = parent.create_dataset(name, data=_char_codes(s).reshape(-1, 1))
            ds.attrs.create("MATLAB_int_decode", np.int32(2))
        _set_class(ds, "char")

    def _write_struct(self, parent: h5py.Group, name: str, fields: dict) -> None:
        grp = parent.create_group(name)
        _set_class(grp, "struct")
        names = []
        for key, val in fields.items():
            if val is None:
                continue
            self._write(grp, str(key), val)
            names.append(str(key))
        vlen = h5py.vlen_dtype(np.dtype("S1"))
        listing = np.empty(len(names), dtype=object)
        for i, nm in enumerate(names):
            listing[i] = np.frombuffer(nm.encode("utf-8"), dtype="S1")
        grp.attrs.create("MATLAB_fields", listing, dtype=vlen)

    def _write_cell_of_char(self, parent: h5py.Group, name: str, strings: list[str]) -> None:
        if self._refs is None:
            self._refs = self._f.require_group("#refs#")
        refs = np.empty(len(strings), dtype=h5py.ref_dtype)
        for i, s in enumerate(strings):
            ref_name = f"c{self._n_refs}"
            self._n_refs += 1
            self._write_char(self._refs, ref_name, s)
            refs[i] = self._refs[ref_name].ref
        ds = parent.create_dataset(name, data=refs.reshape(-1, 1), dtype=h5py.ref_dtype)
        _set_class(ds, "cell")


def mat73_disk_need(n: int, n_cols: int) -> int:
    """Free bytes to require before starting a v7.3 write: the uncompressed DATA size (gzip of
    float64 force data saves little, so assume none) plus 2 % and 256 MB of slack."""
    raw = n * n_cols * 8
    return int(raw * 1.02) + 256 * 1024 * 1024


__all__ = ["Mat73Writer", "USERBLOCK_BYTES", "mat73_disk_need"]
