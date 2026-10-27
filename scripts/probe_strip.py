#!/usr/bin/env python3
"""给一个时间区间，抽 6 帧排成条带图，用来挑「最完整的那一帧」当 --probe。

为什么需要它：按亮度峰值选代表帧经常落在粒子爆开/闪光上，
而 --probe 决定了 bbox、字号、主色，选错整条片子都会跟着错。

用法：
  python probe_strip.py --video in.mp4 --start 30.10 --end 32.60 --out probe.png
"""
import argparse
import json
import math
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

N = 6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cols", type=int, default=3)
    a = ap.parse_args()

    dur = a.end - a.start
    if dur <= 0:
        raise SystemExit("--end must be > --start")

    tmp = os.path.join(os.path.dirname(os.path.abspath(a.out)) or ".", "_probe_tmp")
    os.makedirs(tmp, exist_ok=True)

    times = [a.start + dur * (i + 0.5) / N for i in range(N)]
    rows = []
    frames = []
    for i, t in enumerate(times):
        p = os.path.join(tmp, f"p{i}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", a.video,
                        "-frames:v", "1", p], check=True)
        if not os.path.isfile(p):
            raise SystemExit(f"no frame at {t:.2f}s - check the range against the video duration")
        im = Image.open(p).convert("RGB")
        arr = np.array(im).astype(np.float32) / 255.0
        gry = arr.max(2)

        m = gry > 0.35
        rr = np.where(m.sum(1) > max(4, 0.008 * m.shape[1]))[0]
        cc = np.where(m.sum(0) > max(4, 0.008 * m.shape[0]))[0]
        if len(rr):
            bw = int(cc.max() - cc.min())
            bh = int(rr.max() - rr.min())
            cx = int((cc.min() + cc.max()) / 2)
            cy = int((rr.min() + rr.max()) / 2)
        else:
            bw = bh = cx = cy = 0

        px = arr.reshape(-1, 3)
        lit = px[px.max(1) > 0.55]
        hue = sat = 0.0
        if len(lit) > 50:
            d = lit.max(1) - lit.min(1)
            s = d / np.maximum(lit.max(1), 1e-6)
            den = np.where(d > 1e-6, d, 1e-6)
            h = np.where(lit[:, 0] == lit.max(1), ((lit[:, 1] - lit[:, 2]) / den) % 6,
                         np.where(lit[:, 1] == lit.max(1),
                                  (lit[:, 2] - lit[:, 0]) / den + 2,
                                  (lit[:, 0] - lit[:, 1]) / den + 4)) * 60.0
            sel = s > 0.15
            if sel.sum() >= 30:
                ang = np.radians(h[sel])
                wt = s[sel]
                hue = math.degrees(math.atan2((np.sin(ang) * wt).sum(),
                                              (np.cos(ang) * wt).sum())) % 360
                sat = float(np.median(s[sel]))
        rows.append(dict(t=round(t, 2), bbox=[int(cc.min()), int(cc.max()),
                                              int(rr.min()), int(rr.max())] if len(rr) else None,
                         w=bw, h=bh, cx=cx, cy=cy,
                         hue=round(hue), sat=round(sat, 2),
                         lit_frac=round(float(m.mean()), 3)))
        frames.append(im)

    cw, iw, ih = 460, 460, 259
    cols = a.cols
    rowsn = (N + cols - 1) // cols
    sheet = Image.new("RGB", (cols * iw + 8, rowsn * (ih + 34) + 8), (8, 8, 10))
    d = ImageDraw.Draw(sheet)
    try:
        f1 = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 16)
    except OSError:
        f1 = ImageFont.load_default()
    for i, (im, r) in enumerate(zip(frames, rows)):
        c, rr_ = i % cols, i // cols
        x, y = 4 + c * iw, 4 + rr_ * (ih + 34)
        sheet.paste(im.resize((iw, ih), Image.LANCZOS), (x, y))
        d.rectangle([x, y + ih, x + iw, y + ih + 30], fill=(16, 16, 20))
        d.text((x + 4, y + ih + 3),
               f"#{i + 1} {r['t']:.2f}s  {r['w']}x{r['h']}  hue{r['hue']} sat{r['sat']}",
               fill=(215, 220, 230), font=f1)
        d.text((x + 4, y + ih + 16),
               f"     cx{r['cx']} cy{r['cy']}  lit{r['lit_frac']}",
               fill=(140, 200, 255), font=f1)
    sheet.save(a.out)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)

    print(json.dumps(rows, ensure_ascii=False))
    print(f"\nstrip -> {a.out}")
    print("挑一帧：亮部 w×h 最大、且 lit_frac 不再上涨的那帧最完整；"
          "把它的时间填给 make_wordmark.py 的 --probe。")


if __name__ == "__main__":
    main()
