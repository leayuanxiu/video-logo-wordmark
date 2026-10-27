#!/usr/bin/env python3
"""拿到一个新的模板视频，先跑这个：扫全片，输出每个 logo 的真实可见区间。

为什么不用 make_logo.py analyze：它用 0.25s 采样 + 亮度峰值分段，
起止带 ±0.25s 误差，会把一个标志切成两段、把两个并成一段。
这个脚本逐帧扫亮度，边界精确到 0.1s，并给出每段的峰值帧和主色。

用法：
  python scan_segments.py --video in.mp4 --out segs.png
  # 输出：段表（终端）+ 每段一格缩略图 + segs.json
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

LAT = r"C:\Windows\Fonts\consola.ttf"
CJK = r"C:\Windows\Fonts\msyhbd.ttc"


def palette(arr):
    px = arr.reshape(-1, 3)
    lit = px[px.max(1) > 0.55]
    if len(lit) < 50:
        return 0.0, 0.0
    d = lit.max(1) - lit.min(1)
    s = d / np.maximum(lit.max(1), 1e-6)
    den = np.where(d > 1e-6, d, 1e-6)
    h = np.where(lit[:, 0] == lit.max(1), ((lit[:, 1] - lit[:, 2]) / den) % 6,
                 np.where(lit[:, 1] == lit.max(1), (lit[:, 2] - lit[:, 0]) / den + 2,
                          (lit[:, 0] - lit[:, 1]) / den + 4)) * 60.0
    sel = s > 0.15
    if sel.sum() < 30:
        return 0.0, float(np.median(s))
    ang = np.radians(h[sel])
    wt = s[sel]
    return math.degrees(math.atan2((np.sin(ang) * wt).sum(),
                                   (np.cos(ang) * wt).sum())) % 360, float(np.median(s[sel]))


def bbox(arr, thr=0.35):
    g = arr.max(2)
    m = g > thr
    rr = np.where(m.sum(1) > max(3, 0.008 * m.shape[1]))[0]
    cc = np.where(m.sum(0) > max(3, 0.008 * m.shape[0]))[0]
    if len(rr) == 0 or len(cc) == 0:
        return None
    return int(cc.min()), int(cc.max()), int(rr.min()), int(rr.max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True, help="段缩略图拼图路径，同名写 .json")
    ap.add_argument("--fps", type=float, default=10.0, help="扫描帧率，默认 10（精度 0.1s）")
    ap.add_argument("--gap", type=float, default=0.08, help="小于该值的暗场视为同一段；宁小勿大，细切让用户合并")
    ap.add_argument("--min-dur", type=float, default=0.4, help="短于该值的段丢弃")
    ap.add_argument("--thr", type=float, default=None, help="手动指定亮度阈值")
    ap.add_argument("--cols", type=int, default=6)
    a = ap.parse_args()

    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-show_entries", "format=duration", "-of", "json", a.video],
        capture_output=True, text=True, check=True).stdout)
    W = int(info["streams"][0]["width"])
    H = int(info["streams"][0]["height"])
    dur = float(info["format"]["duration"])

    tmp = tempfile.mkdtemp(prefix="scan_")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.video,
                        "-vf", f"fps={a.fps},scale=480:-2", os.path.join(tmp, "f_%05d.png")],
                       check=True)
        files = sorted(os.listdir(tmp))
        if not files:
            raise SystemExit("no frames decoded")

        lum, frames = [], []
        for f in files:
            arr = np.array(Image.open(os.path.join(tmp, f)).convert("RGB")).astype(np.float32) / 255.0
            frames.append(arr)
            lum.append(float(arr.mean()))
        lum = np.array(lum)
        thr = a.thr if a.thr is not None else max(0.003, float(np.percentile(lum, 98)) * 0.05)

        on = lum > thr
        runs, st = [], None
        for i, v in enumerate(on):
            if v and st is None:
                st = i
            elif not v and st is not None:
                runs.append([st, i - 1])
                st = None
        if st is not None:
            runs.append([st, len(on) - 1])

        merged = []
        for r in runs:
            if merged and (r[0] - merged[-1][1]) / a.fps <= a.gap:
                merged[-1][1] = r[1]
            else:
                merged.append(list(r))

        segs = []
        for r in merged:
            d = (r[1] - r[0] + 1) / a.fps
            if d < a.min_dur:
                continue
            t0, t1 = r[0] / a.fps, r[1] / a.fps
            pk = r[0] + int(np.argmax(lum[r[0]:r[1] + 1]))
            arr = frames[pk]
            hu, sa = palette(arr)
            bb = bbox(arr)
            segs.append(dict(start=round(t0, 1), end=round(t1, 1), dur=round(d, 1),
                             peak_t=round(pk / a.fps, 1),
                             hue=round(hu), sat=round(sa, 2),
                             bbox=[round(v * W / 480) for v in bb] if bb else None))

        # 相邻段若色相和水平中心都很接近，多半是同一个标志被动画里的暗谷切开了
        for i, s in enumerate(segs):
            s["same_as"] = None
            if i and segs[i - 1]["bbox"] and s["bbox"]:
                p = segs[i - 1]
                dx = abs((p["bbox"][0] + p["bbox"][1]) / 2 - (s["bbox"][0] + s["bbox"][1]) / 2)
                dh = abs((p["hue"] - s["hue"] + 180) % 360 - 180)
                if dh < 25 and dx < W * 0.12 and (s["start"] - p["end"]) <= 0.7:
                    s["same_as"] = i

        out_json = os.path.splitext(a.out)[0] + ".json"
        json.dump(dict(video=os.path.basename(a.video), w=W, h=H, dur=round(dur, 2),
                       thr=round(thr, 4), segments=segs), open(out_json, "w"),
                  ensure_ascii=False, indent=1)

        print(f"{os.path.basename(a.video)}  {W}x{H}  {dur:.2f}s  thr={thr:.4f}")
        print(f"{len(segs)} 段\n")
        print("  #   start    end   dur  peak_t   hue  sat    bbox")
        for i, s in enumerate(segs, 1):
            bb = s["bbox"]
            bbs = f"{bb[0]}-{bb[1]},{bb[2]}-{bb[3]}" if bb else "-"
            tie = f"  ≈#{s['same_as']}" if s.get("same_as") else ""
            print(f"  {i:<3} {s['start']:6.1f} {s['end']:6.1f} {s['dur']:5.1f} "
                  f"{s['peak_t']:7.1f} {s['hue']:5.0f} {s['sat']:.2f}   {bbs}{tie}")

        cw, ch = 300, 169
        cols = a.cols
        rows = max(1, (len(segs) + cols - 1) // cols)
        sheet = Image.new("RGB", (cols * cw + 8, rows * (ch + 30) + 8), (8, 8, 10))
        d = ImageDraw.Draw(sheet)
        try:
            f1 = ImageFont.truetype(CJK, 15)
            f2 = ImageFont.truetype(LAT, 13)
        except OSError:
            f1 = f2 = ImageFont.load_default()
        for i, s in enumerate(segs):
            c, r = i % cols, i // cols
            x, y = 4 + c * cw, 4 + r * (ch + 30)
            pk = int(round(s["peak_t"] * a.fps))
            th = Image.fromarray((frames[min(pk, len(frames) - 1)] * 255).astype(np.uint8))
            sheet.paste(th.resize((cw, ch), Image.LANCZOS), (x, y))
            d.text((x + 3, y + ch + 1), f"{i + 1}.  {s['start']:.1f}-{s['end']:.1f}s",
                   fill=(255, 215, 60), font=f2)
            d.text((x + 3, y + ch + 15), f"   peak {s['peak_t']:.1f}s  hue{s['hue']}",
                   fill=(150, 195, 235), font=f2)
        sheet.save(a.out)

        print(f"\nsheet -> {a.out}")
        print(f"json  -> {out_json}")
        print("把拼图发给用户点编号；区间要给用户确认（脚本精度 0.1s，不是帧级）。")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()



