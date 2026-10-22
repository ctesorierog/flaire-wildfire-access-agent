"""flAIre · FireScope (INSAIT) window for Tolosaldea — reproducible version of the browser step.

What it does (same as the browser extraction of 2 Oct 2026):
  1. Reads the BigTIFF header of europe_risk.tif (12.3 GB, EPSG:3857, 30 m, uint8, LZW, 512x512 tiles,
     origin x=-1176450, y=11467830, nodata 255) with HTTP Range requests only.
  2. Downloads just the tiles covering lon -2.26..-1.86, lat 42.97..43.29 (20 tiles, ~1.7 MB), decodes LZW
     with Pillow/tifffile-free pure Python, writes raw/firescope/firescope_tolosaldea_window.{bin,json}.
  3. `sample` mode: GeoTIFF + per-building index (mean of 9x9 px window ≈ ±90 m) for agent/datos/edificios.csv
     -> processed/firescope/firescope_buildings.csv (fs_px, fs_mean100, fs_max100).

Needs network access to huggingface.co (blocked in the cloud sandbox; it was run from the team browser).
Usage:  python3 code/firescope_window.py download      # steps 1-2
        python3 code/firescope_window.py sample        # step 3 (offline)
Source: https://huggingface.co/datasets/INSAIT-Institute/firescope-risk-2026 (CC BY 4.0); arXiv 2511.17171.
"""
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://huggingface.co/datasets/INSAIT-Institute/firescope-risk-2026/resolve/main/europe_risk.tif"
W, H, T = 210056, 247907, 512
X0, Y0, PX, R = -1176450.0, 11467830.0, 30.0, 6378137.0
OFFSETS_AT, COUNTS_AT = 797732, 392          # from IFD0 tags 324 (LONG8) and 325 (LONG)
BBOX = (-2.26, 42.97, -1.86, 43.29)


def _rng(a, b):
    import urllib.request
    req = urllib.request.Request(URL, headers={"Range": f"bytes={a}-{b}"})
    with urllib.request.urlopen(req) as r:
        return r.read()


def lzw_decode(src: bytes) -> bytes:
    out = bytearray()
    dic = [bytes([i]) for i in range(256)] + [b"", b""]
    bits, pos, prev = 9, 0, None
    nbits = len(src) * 8
    while pos + bits <= nbits:
        v = 0
        for i in range(bits):
            v = (v << 1) | ((src[(pos + i) >> 3] >> (7 - ((pos + i) & 7))) & 1)
        pos += bits
        if v == 257:
            break
        if v == 256:
            dic = dic[:258]
            bits, prev = 9, None
            continue
        if v < len(dic):
            entry = dic[v]
        elif prev is not None:
            entry = prev + prev[:1]
        else:
            break
        out += entry
        if prev is not None:
            dic.append(prev + entry[:1])
        prev = entry
        if len(dic) + 1 >= (1 << bits) and bits < 12:
            bits += 1
    return bytes(out)


def download():
    mx = lambda lon: math.radians(lon) * R
    my = lambda lat: R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    c0 = int((mx(BBOX[0]) - X0) // PX); c1 = math.ceil((mx(BBOX[2]) - X0) / PX)
    r0 = int((Y0 - my(BBOX[3])) // PX); r1 = math.ceil((Y0 - my(BBOX[1])) / PX)
    tc0, tc1, tr0, tr1 = c0 // T, c1 // T, r0 // T, r1 // T
    tcols = math.ceil(W / T)
    MW, MH = (tc1 - tc0 + 1) * T, (tr1 - tr0 + 1) * T
    mos = bytearray([255]) * (MW * MH)
    for tr in range(tr0, tr1 + 1):
        i0, i1 = tr * tcols + tc0, tr * tcols + tc1
        offs = struct.unpack(f"<{i1 - i0 + 1}Q", _rng(OFFSETS_AT + 8 * i0, OFFSETS_AT + 8 * i1 + 7))
        cnts = struct.unpack(f"<{i1 - i0 + 1}I", _rng(COUNTS_AT + 4 * i0, COUNTS_AT + 4 * i1 + 3))
        for k, (o, n) in enumerate(zip(offs, cnts)):
            if not n:
                continue
            px = lzw_decode(_rng(o, o + n - 1))
            for y in range(T):
                row = ((tr - tr0) * T + y) * MW + k * T
                mos[row:row + T] = px[y * T:(y + 1) * T]
    w, h = c1 - c0 + 1, r1 - r0 + 1
    win = bytearray(w * h)
    for y in range(h):
        sy = (r0 + y) - tr0 * T
        win[y * w:(y + 1) * w] = mos[sy * MW + (c0 - tc0 * T): sy * MW + (c0 - tc0 * T) + w]
    out = ROOT / "raw" / "firescope"
    out.mkdir(parents=True, exist_ok=True)
    (out / "firescope_tolosaldea_window.bin").write_bytes(bytes(win))
    meta = dict(source=URL, crs="EPSG:3857", pixel_m=30, dtype="uint8", nodata=255, width=w, height=h,
                window_col0=c0, window_row0=r0, window_x0=X0 + c0 * PX, window_y0=Y0 - r0 * PX)
    (out / "firescope_tolosaldea_window.json").write_text(json.dumps(meta, indent=1))
    print("window", w, "x", h)


def sample():
    import numpy as np
    import pandas as pd
    from pyproj import Transformer
    m = json.loads((ROOT / "raw/firescope/firescope_tolosaldea_window.json").read_text())
    a = np.fromfile(ROOT / "raw/firescope/firescope_tolosaldea_window.bin", dtype=np.uint8).reshape(m["height"], m["width"])
    af = a.astype(float); af[a == 255] = np.nan
    b = pd.read_csv(ROOT / "agent/datos/edificios.csv", dtype={"building_id": str})
    X, Y = Transformer.from_crs(4326, 3857, always_xy=True).transform(b.lon.values, b.lat.values)
    c = ((X - m["window_x0"]) / m["pixel_m"]).astype(int); r = ((m["window_y0"] - Y) / m["pixel_m"]).astype(int)
    k = 4
    b["fs_px"] = af[r, c]
    b["fs_mean100"] = [np.nanmean(af[i - k:i + k + 1, j - k:j + k + 1]) for i, j in zip(r, c)]
    b["fs_max100"] = [np.nanmax(af[i - k:i + k + 1, j - k:j + k + 1]) for i, j in zip(r, c)]
    out = ROOT / "processed/firescope"; out.mkdir(parents=True, exist_ok=True)
    b[["building_id", "fs_px", "fs_mean100", "fs_max100"]].to_csv(out / "firescope_buildings.csv", index=False)
    print(b[["fs_px", "fs_mean100"]].describe())


if __name__ == "__main__":
    {"download": download, "sample": sample}[sys.argv[1] if len(sys.argv) > 1 else "sample"]()
