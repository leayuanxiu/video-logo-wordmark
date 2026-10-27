#!/usr/bin/env python3
"""Stamp a Chinese wordmark onto a logo animation taken from a video.

能力：
  1. 配色自适应：从标志本身取主色，字/光晕/细线都跟着变。
  2. 版式：bottom / top / left / right / center（字在图形外）
     over_sign / over_hero（字压在图形上：签名式小字 / 主标题式大字）
  3. 边缘分离：字外一圈同色相暗环，同色压字也不糊。
  4. 穿字线、数字串副标（仿 FINDING 那种排版）。
  5. 字宽按墨迹实测反解；字高受标志高封顶。

用法：
  python make_wordmark.py --video in.mp4 --start 0 --end 4.5 --probe 3.0 \
      --layout bottom --name moci_lotus --outdir out
  python make_wordmark.py --video in.mp4 --start 30.4 --end 33.4 --probe 31.5 \
      --layout over_hero --rules-through --num "2 2 0 8 0 1 8 0 8 0 5" \
      --name moci_hero --outdir out
"""
import argparse
import colorsys
import json
import math
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\yezigongchangmengchanganxingkai.ttf"),
    r"C:\Windows\Fonts\STXINGKA.TTF",
    r"C:\Windows\Fonts\STKAITI.TTF",
    r"C:\Windows\Fonts\simkai.ttf",
]
LAT_CANDIDATES = [r"C:\Windows\Fonts\pala.ttf", r"C:\Windows\Fonts\georgia.ttf"]

LAYOUTS = ["bottom", "top", "left", "right", "center", "over_sign", "over_hero"]


def pick(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def blur(a, r):
    im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    return np.array(im.filter(ImageFilter.GaussianBlur(max(0.1, r)))).astype(np.float32) / 255.0


def dilate(a, px):
    im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    return np.array(im.filter(ImageFilter.MaxFilter(int(px) * 2 + 1))).astype(np.float32) / 255.0


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def shift(m, dy):
    dy = int(round(dy))
    if dy == 0:
        return m
    o = np.zeros_like(m)
    if dy > 0:
        o[dy:] = m[:-dy]
    else:
        o[:dy] = m[-dy:]
    return o


def hx(h, s, v):
    return colorsys.hsv_to_rgb((h % 360) / 360.0, min(max(s, 0), 1), min(max(v, 0), 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--probe", type=float, default=0.0,
                    help="已成形那一帧的绝对时间，用来量 bbox 和主色")
    ap.add_argument("--text", default="\\u83ab\\u8f9e", help="字标；\\uXXXX 转义最稳")
    ap.add_argument("--sub", default="M O C I", help="下方拉丁小字（over_* 默认不画）")
    ap.add_argument("--layout", default="bottom", choices=LAYOUTS)
    ap.add_argument("--size-key", type=float, default=None,
                    help="字宽 = 该值 x 亮部宽。默认：外置 0.70 / over_sign 0.28 / over_hero 0.78")
    ap.add_argument("--gap", type=float, default=46, help="外置布局：标志边到字边的间距 px")
    ap.add_argument("--over-pos", default=None,
                    help="over_* 的字心坐标，归一化 '0.72,0.80'；不给用布局默认点")
    ap.add_argument("--edge-sep", type=float, default=0.75,
                    help="字外暗环强度 0~1，同色压字时靠它和标志分开")
    ap.add_argument("--rules-through", action="store_true",
                    help="画一条穿过字中线的横线（仿 FINDING）")
    ap.add_argument("--num", default="", help="数字串副标，空=不画")
    ap.add_argument("--text-in", type=float, default=None, help="字开始淡入的绝对时间")
    ap.add_argument("--ramp", type=float, default=0.62)
    ap.add_argument("--text-out", type=float, default=None, help="字开始淡出的绝对时间")
    ap.add_argument("--ramp-out", type=float, default=0.32)
    ap.add_argument("--thr", type=float, default=0.35, help="量亮部的亮度阈值")
    ap.add_argument("--no-rules", action="store_true", help="外置布局：不要两侧细线")
    ap.add_argument("--still-only", action="store_true",
                    help="只渲染 still 那一帧，不编码（layout_sheet 用来快速试排）")
    ap.add_argument("--hue", type=float, default=None, help="强制字色相 0-360，覆盖自动取色")
    ap.add_argument("--sat", type=float, default=None, help="强制饱和度 0-1，覆盖自动取色")
    ap.add_argument("--track", type=float, default=0.08, help="字距，相对字号；正=更开")
    ap.add_argument("--font")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--name", required=True)
    ap.add_argument("--outdir", default=".")
    a = ap.parse_args()

    if "\\u" in a.text:
        a.text = a.text.encode("ascii", "ignore").decode("unicode_escape")

    font = a.font or pick(FONT_CANDIDATES)
    if not font:
        raise SystemExit("no CJK font; pass --font")
    lat = pick(LAT_CANDIDATES)

    probe_info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", a.video],
        capture_output=True, text=True, check=True).stdout)["streams"][0]
    W, H = int(probe_info["width"]), int(probe_info["height"])
    FPS = a.fps
    over = a.layout.startswith("over")

    dur = a.end - a.start
    N = int(round(dur * FPS))
    outdir = os.path.abspath(a.outdir)
    os.makedirs(outdir, exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="wm_")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a.start), "-t", str(dur),
                        "-i", a.video, "-vf", f"fps={FPS}", os.path.join(tmp, "s_%04d.png")],
                       check=True)
        files = sorted(f for f in os.listdir(tmp) if f.startswith("s_"))
        if not files:
            raise SystemExit("no frames extracted; check --start/--end")

        probe_t = a.probe if a.probe else (a.start + a.end) / 2
        pidx = min(len(files) - 1, max(0, int(round((probe_t - a.start) * FPS))))
        probe = np.array(Image.open(os.path.join(tmp, files[pidx])).convert("RGB")).astype(np.float32) / 255.0

        gry = probe.max(2)
        m = gry > a.thr
        rr = np.where(m.sum(1) > max(4, 0.008 * m.shape[1]))[0]
        cc = np.where(m.sum(0) > max(4, 0.008 * m.shape[0]))[0]
        if len(rr) == 0 or len(cc) == 0:
            raise SystemExit("mark not found on probe frame; raise --probe or lower --thr")
        x0, x1, y0, y1 = int(cc.min()), int(cc.max()), int(rr.min()), int(rr.max())
        bw, bh = x1 - x0, y1 - y0

        px = probe.reshape(-1, 3)
        lit = px[px.max(1) > 0.55]
        if len(lit) < 50:
            HUE, SAT = 300.0, 0.20
        else:
            d = lit.max(1) - lit.min(1)
            s = d / np.maximum(lit.max(1), 1e-6)
            den = np.where(d > 1e-6, d, 1e-6)
            h = np.where(lit[:, 0] == lit.max(1), ((lit[:, 1] - lit[:, 2]) / den) % 6,
                         np.where(lit[:, 1] == lit.max(1),
                                  (lit[:, 2] - lit[:, 0]) / den + 2,
                                  (lit[:, 0] - lit[:, 1]) / den + 4)) * 60.0
            sel = s > 0.15
            if sel.sum() < 30:
                HUE, SAT = 300.0, 0.12
            else:
                ang = np.radians(h[sel])
                wt = s[sel]
                HUE = math.degrees(math.atan2((np.sin(ang) * wt).sum(),
                                              (np.cos(ang) * wt).sum())) % 360
                SAT = float(np.median(s[sel]))

        if a.hue is not None:
            HUE = a.hue % 360
        if a.sat is not None:
            SAT = min(max(a.sat, 0.0), 1.0)

        def glyphs(size, track=0.08):
            fp = ImageFont.truetype(font, size)
            d0 = ImageDraw.Draw(Image.new("L", (8, 8)))
            adv = [d0.textlength(c, font=fp) for c in a.text]
            tk = int(size * track)
            lay = Image.new("L", (int(sum(adv) + tk * (len(a.text) - 1)) + size * 2,
                                  int(size * 2)), 0)
            d = ImageDraw.Draw(lay)
            x = size * 0.5
            for c, ad in zip(a.text, adv):
                d.text((x, size * 0.5), c, font=fp, fill=255, anchor="la")
                x += ad + tk
            return lay.crop(lay.getbbox())

        key = a.size_key
        if key is None:
            key = 0.28 if a.layout == "over_sign" else (0.78 if a.layout == "over_hero" else 0.70)
        size = 200
        for _ in range(5):
            g = glyphs(size, a.track)
            size = max(24, int(round(size * (bw * key) / max(g.size[0], 1))))
        ink = glyphs(size, a.track)
        iw, ih = ink.size
        max_ih = int(bh * (1.6 if over else 0.66))
        capped = ih > max_ih > 0
        if capped:
            size = max(20, int(size * max_ih / ih))
            ink = glyphs(size, a.track)
            iw, ih = ink.size

        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if a.layout == "bottom":
            cy = y1 + a.gap + ih / 2
        elif a.layout == "top":
            cy = y0 - a.gap - ih / 2
        elif a.layout == "right":
            cx = x1 + a.gap + iw / 2
        elif a.layout == "left":
            cx = x0 - a.gap - iw / 2
        elif a.layout == "over_sign":
            cx, cy = x1 - bw * 0.16, y1 - bh * 0.12
        elif a.layout == "over_hero":
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if over and a.over_pos:
            fx, fy = [float(v) for v in a.over_pos.split(",")]
            cx, cy = x0 + bw * fx, y0 + bh * fy
        cx = min(max(cx, iw / 2 + 44), W - iw / 2 - 44)
        cy = min(max(cy, ih / 2 + 44), H - ih / 2 - 54)

        MASK = np.zeros((H, W), np.float32)
        MASK[int(cy - ih / 2):int(cy - ih / 2) + ih,
             int(cx - iw / 2):int(cx - iw / 2) + iw] = np.array(ink).astype(np.float32) / 255.0

        stops = [(0.00, hx(HUE, SAT * 0.30, 1.00)), (0.25, hx(HUE, SAT * 0.72, 1.00)),
                 (0.60, hx(HUE, SAT * 0.95, 0.93)), (1.00, hx(HUE + 10, SAT * 1.00, 0.58))]
        GLOWC = np.array(hx(HUE, min(SAT * 1.1, 0.9), 1.0), np.float32)
        DCOL = np.array(hx(HUE, min(SAT * 0.85, 0.65), 1.0), np.float32)

        DEC = Image.new("L", (W, H), 0)
        dd = ImageDraw.Draw(DEC)
        if over:
            if a.rules_through:
                ly = int(cy)
                xa, xb = x0 - 70, x1 + 70
                span = int(xb - xa)
                for i in range(span):
                    k = i / max(span - 1, 1)
                    edge = min(1.0, 6 * min(k, 1 - k))
                    dd.line([(xa + i, ly), (xa + i, ly + 2)], fill=int(215 * edge))
            if a.num and lat:
                d0 = ImageDraw.Draw(Image.new("L", (8, 8)))
                target = iw * 1.08                       # 数字串宽度跟着字走，别撑满全幅
                ssz = max(10, int(size * 0.20))
                for _ in range(4):
                    fp = ImageFont.truetype(lat, ssz)
                    adv = [d0.textlength(c, font=fp) for c in a.num]
                    tk = int(ssz * 0.75)
                    tot = sum(adv) + tk * (len(a.num) - 1)
                    if tot <= target or ssz <= 10:
                        break
                    ssz = max(10, int(ssz * target / max(tot, 1)))
                fp = ImageFont.truetype(lat, ssz)
                adv = [d0.textlength(c, font=fp) for c in a.num]
                tk = int(ssz * 0.75)
                tot = sum(adv) + tk * (len(a.num) - 1)
                xx = cx - tot / 2
                ny = int(cy + ih * 0.58)
                for ch, ad in zip(a.num, adv):
                    dd.text((xx, ny), ch, font=fp, fill=235)
                    xx += ad + tk
                ly2 = int(ny + ssz * 1.9)
                xa, xb = x0 - 70, x1 + 70
                span = int(xb - xa)
                for i in range(span):
                    k = i / max(span - 1, 1)
                    edge = min(1.0, 6 * min(k, 1 - k))
                    dd.line([(xa + i, ly2), (xa + i, ly2 + 1)], fill=int(150 * edge))
        else:
            if not a.no_rules:
                linelen = int(iw * 0.24)
                ry = int(cy - ih * 0.01)
                for sgn in (-1, 1):
                    for i in range(linelen):
                        k = i / max(linelen - 1, 1)
                        al = int(240 * (min(1.0, k * 5) ** 0.55) * (1 - 0.5 * k ** 2))
                        xx = cx + sgn * (iw / 2 + 26 + i)
                        dd.line([(xx, ry - 1), (xx, ry + 1)], fill=al)
            if a.sub and lat:
                fp = ImageFont.truetype(lat, max(10, int(size * 0.215)))
                d0 = ImageDraw.Draw(Image.new("L", (8, 8)))
                advs = [d0.textlength(c, font=fp) for c in a.sub]
                tk = int(size * 0.215 * 0.85)
                tot = sum(advs) + tk * (len(a.sub) - 1)
                xx = cx - tot / 2
                for ch, ad in zip(a.sub, advs):
                    dd.text((xx, cy + ih * 0.36 + 26), ch, font=fp, fill=245)
                    xx += ad + tk
        DEC = np.array(DEC).astype(np.float32) / 255.0

        t_in = (a.text_in - a.start) if a.text_in is not None else max(0.10, (probe_t - a.start) + 0.05)
        t_out = (a.text_out - a.start) if a.text_out is not None else max(t_in + 0.4, dur - 0.30)

        rgbd = os.path.join(tmp, "rgb")
        alpd = os.path.join(tmp, "alp")
        os.makedirs(rgbd)
        os.makedirs(alpd)

        G1 = blur(MASK, max(2, ih * 0.04))
        G2 = blur(MASK, max(4, ih * 0.16))
        edge_ring = np.clip(dilate(MASK, max(2, int(size * 0.018))) - MASK, 0, 1)
        edge_ring = blur(edge_ring, max(0.8, size * 0.010)) * a.edge_sep
        scrim = None
        if over:
            scrim = blur(MASK, size * 0.09) * (0.30 if a.layout == "over_hero" else 0.15)
        occ = None
        if a.layout == "center":
            yc0, yc1 = max(0, int(cy - ih / 2)), min(H, int(cy + ih / 2))
            xc0, xc1 = max(0, int(cx - iw / 2)), min(W, int(cx + iw / 2))
            fill = float(gry[yc0:yc1, xc0:xc1].mean()) if (yc1 > yc0 and xc1 > xc0) else 1.0
            if fill > 0.22:
                print(f"WARNING: centre fill={fill:.2f} > 0.22 — the mark is solid behind the "
                      f"text, wordmark will be shredded. Use --layout bottom/top/left/right.")
            occ = blur(np.clip((gry - 0.04) / 0.80, 0, 1), max(3, size * 0.05)) * 0.50

        still_t = min(max(t_in + a.ramp + 0.25, 0.0), dur - 1.0 / FPS)
        still_idx = max(0, min(N - 1, int(round(still_t * FPS))))
        idx_list = [still_idx] if a.still_only else list(range(N))

        for i in idx_list:
            fn = files[i]
            t = i / FPS
            r_in = ease((t - t_in) / max(a.ramp, 1e-3)) if t > t_in else 0.0
            r_out = 1 - ease((t - t_out) / max(a.ramp_out, 1e-3))
            al = max(0.0, r_in * r_out)
            dy = 16 * (1 - r_in)
            src = np.array(Image.open(os.path.join(tmp, fn)).convert("RGB")).astype(np.float32) / 255.0
            if al > 0.002:
                m_ = shift(MASK, dy) * al
                d_ = shift(DEC, dy) * al
                if scrim is not None:
                    src = src * (1 - shift(scrim, dy)[..., None] * al)
                src = src * (1 - shift(edge_ring, dy)[..., None] * al)
                aa = m_ if occ is None else m_ * np.clip(1 - occ, 0, 1)
                src = src * (1 - d_[..., None]) + DCOL[None, None, :] * d_[..., None]
                top = int(cy - ih / 2 + dy)
                tt = np.clip((np.arange(H, dtype=np.float32) - top) / max(ih, 1), 0, 1) ** 1.05
                colv = np.zeros((H, 3), np.float32)
                for q in range(len(stops) - 1):
                    p0, c0 = stops[q]
                    p1, c1 = stops[q + 1]
                    mm = (tt >= p0) & (tt <= p1)
                    kk = ((tt - p0) / (p1 - p0))[mm][:, None]
                    colv[mm] = (1 - kk) * np.array(c0, np.float32) + kk * np.array(c1, np.float32)
                img = np.repeat(colv[:, None, :], W, axis=1)
                src = src * (1 - aa[..., None]) + img * aa[..., None]
                src = src + GLOWC[None, None, :] * (
                    (shift(G1, dy) * 0.10 + shift(G2, dy) * 0.12) * al)[..., None]
            src = np.clip(src, 0, 1)
            Image.fromarray((src * 255 + 0.5).astype(np.uint8)).save(
                os.path.join(rgbd, f"f_{i:04d}.png"))
            aa2 = np.clip((src.max(2) - 0.040) / 0.90, 0, 1) ** 1.15
            aa2 = blur(aa2, 0.7)
            st = np.where(aa2[..., None] > 0.004,
                          np.clip(src / np.maximum(aa2[..., None], 1e-4), 0, 1), 0)
            Image.fromarray((np.dstack([st, aa2]) * 255 + 0.5).astype(np.uint8)).save(
                os.path.join(alpd, f"f_{i:04d}.png"))

        if a.still_only:
            still_only_png = os.path.join(outdir, f"{a.name}_still.png")
            shutil.copy2(os.path.join(rgbd, f"f_{still_idx:04d}.png"), still_only_png)
            print(json.dumps(dict(name=a.name, layout=a.layout, still=still_only_png,
                                  at=[round(cx), round(cy)], size=size, capped=capped),
                             ensure_ascii=False))
            return

        mp4 = os.path.join(outdir, f"{a.name}.mp4")
        webm = os.path.join(outdir, f"{a.name}_alpha.webm")
        still = os.path.join(outdir, f"{a.name}_still.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS),
                        "-i", os.path.join(rgbd, "f_%04d.png"),
                        "-c:v", "libx264", "-preset", "slow", "-crf", "15",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS),
                        "-i", os.path.join(alpd, "f_%04d.png"),
                        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0",
                        "-crf", "24", "-row-mt", "1", "-auto-alt-ref", "0",
                        "-cpu-used", "3", webm], check=True)
        shutil.copy2(os.path.join(rgbd, f"f_{still_idx:04d}.png"), still)

        chk = os.path.join(tmp, "chk.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-c:v", "libvpx-vp9",
                        "-ss", f"{dur / 2:.2f}", "-i", webm, "-frames:v", "1",
                        "-pix_fmt", "rgba", chk], check=True)
        arr = np.array(Image.open(chk).convert("RGBA")).astype(np.float32) / 255.0
        mean_a, corner_a = float(arr[..., 3].mean()), float(arr[0, 0, 3])

        print(json.dumps(dict(name=a.name, dur=round(dur, 2), layout=a.layout,
                              capped=capped,
                              bbox=[x0, x1, y0, y1], size=size, ink=[iw, ih],
                              at=[round(cx), round(cy)], hue=round(HUE, 1),
                              sat=round(SAT, 3), t_in=round(t_in, 2), t_out=round(t_out, 2),
                              alpha_mean=round(mean_a, 4), alpha_corner=round(corner_a, 3),
                              mp4=os.path.getsize(mp4), webm=os.path.getsize(webm)),
                         ensure_ascii=False))
        if mean_a < 0.005 or corner_a > 0.5:
            print("WARNING: alpha looks wrong - decode with -c:v libvpx-vp9 when checking")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()


