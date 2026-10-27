#!/usr/bin/env python3
"""Stamp a Chinese wordmark onto a logo animation taken from a video.

Sub-commands
------------
analyze  : find the logo segments in a montage video + write a timecoded contact sheet
build    : cut one segment, add the wordmark, encode MP4 + transparent WebM

Both sub-commands need ffmpeg/ffprobe on PATH, plus numpy and Pillow.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# Windows fonts that read as "artistic Chinese"; first hit wins.
FONT_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\yezigongchangmengchanganxingkai.ttf"),
    r"C:\Windows\Fonts\STXINGKA.TTF",
    r"C:\Windows\Fonts\STKAITI.TTF",
    r"C:\Windows\Fonts\simkai.ttf",
]
LATIN_CANDIDATES = [r"C:\Windows\Fonts\pala.ttf", r"C:\Windows\Fonts\georgia.ttf"]


# --------------------------------------------------------------------------- utils
def sh(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-2000:] + "\n")
        raise SystemExit(f"command failed: {' '.join(cmd[:6])} ...")
    return p.stdout


def probe(path):
    out = sh([FFPROBE, "-v", "error", "-select_streams", "v:0",
              "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
              "-show_entries", "format=duration", "-of", "json", path])
    d = json.loads(out)
    st = d["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    return dict(w=int(st["width"]), h=int(st["height"]),
                fps=float(num) / float(den), dur=float(d["format"]["duration"]))


def pick_font(explicit=None):
    for c in ([explicit] if explicit else []) + FONT_CANDIDATES:
        if c and os.path.isfile(c):
            return c
    raise SystemExit("no suitable CJK font found; pass --font <path-to-ttf>")


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def blur(a, r):
    if r <= 0.5:
        return a
    im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    return np.array(im.filter(ImageFilter.GaussianBlur(r))).astype(np.float32) / 255.0


# --------------------------------------------------------------------------- analyze
def cmd_analyze(a):
    info = probe(a.video)
    step = a.interval
    dense = a.dense
    with tempfile.TemporaryDirectory() as tmp:
        # dense pass, tiny frames: count lit pixels to find where a mark is on screen
        sh([FFMPEG, "-v", "error", "-i", a.video, "-vf",
            f"fps={1/dense},scale=320:-1", os.path.join(tmp, "d_%04d.png"), "-y"])
        dense_files = sorted(glob.glob(os.path.join(tmp, "d_*.png")))
        counts = []
        for p in dense_files:
            g = np.array(Image.open(p).convert("L"))
            counts.append(int((g > 40).sum()))
        thr = max(30, int(0.0015 * 320 * 180))
        active = [c > thr for c in counts]
        raw, start = [], None
        for i, on in enumerate(active + [False]):
            if on and start is None:
                start = i
            elif not on and start is not None:
                if (i - start) * dense >= 0.5:
                    raw.append([start * dense, min(i * dense, info["dur"])])
                start = None
        # merge across very short black gaps only (a real cut has >=0.2s of dark)
        merged = []
        for s in raw:
            if merged and s[0] - merged[-1][1] <= 0.22:
                merged[-1][1] = s[1]
            else:
                merged.append(list(s))
        # a fade-in starts dim: reach back one sample, but never into the previous mark
        segs = []
        for k, s in enumerate(merged):
            floor = merged[k - 1][1] + 0.1 if k else 0.0
            segs.append([max(floor, s[0] - dense), s[1]])

        print(f"{os.path.basename(a.video)}  {info['w']}x{info['h']}  "
              f"{info['fps']:.0f}fps  {info['dur']:.2f}s")
        print(f"{len(segs)} segment(s) detected:\n")
        print("  #   start    end   dur   peak%  best-t")
        for i, (s, e) in enumerate(segs, 1):
            lo, hi = int(s / dense), max(int(e / dense), int(s / dense) + 1)
            window = counts[lo:hi] or [0]
            peak = max(window) / (320 * 180) * 100
            best_t = (lo + window.index(max(window))) * dense
            print(f"  {i:<3} {s:6.2f} {e:6.2f} {e - s:5.2f}  {peak:5.1f}  {best_t:5.2f}")

        # sparse pass for the contact sheet
        sh([FFMPEG, "-v", "error", "-i", a.video, "-vf",
            f"fps={1/step},scale=480:-1", "-q:v", "2", os.path.join(tmp, "p_%03d.jpg"), "-y"])
        files = sorted(glob.glob(os.path.join(tmp, "p_*.jpg")))
        cols, tw, th = 4, 480, 270
        rows = max(1, (len(files) + cols - 1) // cols)
        sheet = Image.new("RGB", (cols * (tw + 8) + 8, rows * (th + 34) + 8), (16, 14, 20))
        d = ImageDraw.Draw(sheet)
        try:
            f1 = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeui.ttf"), 18)
        except OSError:
            f1 = ImageFont.load_default()
        for i, p in enumerate(files):
            r, c = divmod(i, cols)
            x, y = 8 + c * (tw + 8), 8 + r * (th + 34)
            sheet.paste(Image.open(p).convert("RGB"), (x, y))
            t = i * step
            d.rectangle([x, y, x + 44, y + 24], fill=(10, 8, 12))
            d.text((x + 6, y + 2), str(i + 1), font=f1, fill=(255, 210, 90))
            d.text((x, y + th + 4), f"{int(t // 60)}:{t % 60:04.1f}", font=f1, fill=(150, 140, 160))
        out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.video)), "contact_sheet.png")
        sheet.save(out)
        print(f"\ncontact sheet -> {out}")
        print("Show it and ask WHICH one before building anything.")


# --------------------------------------------------------------------------- build
def text_mask(text, font_path, size, track_px, W, H, top, align_x):
    fp = ImageFont.truetype(font_path, size)
    probe_d = ImageDraw.Draw(Image.new("L", (8, 8)))
    adv = [probe_d.textlength(c, font=fp) for c in text]
    total = sum(adv) + track_px * (len(text) - 1)
    x = align_x - total / 2
    lay = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(lay)
    cx = x
    for c, w in zip(text, adv):
        d.text((cx, top), c, font=fp, fill=255, anchor="la")
        cx += w + track_px
    return np.array(lay).astype(np.float32) / 255.0, total, x


def cmd_build(a):
    # allow "\u83ab\u8f9e" so the text survives shells that mangle CJK argv
    if "\\u" in a.text:
        a.text = a.text.encode("ascii", "ignore").decode("unicode_escape")
    info = probe(a.video)
    W, H, fps = info["w"], info["h"], a.fps or round(info["fps"])
    dur = min(a.end, info["dur"]) - a.start
    n = int(round(dur * fps))
    font = pick_font(a.font)
    outdir = os.path.abspath(a.outdir)
    os.makedirs(outdir, exist_ok=True)
    name = a.name

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        rgbd = os.path.join(tmp, "rgb")
        alpd = os.path.join(tmp, "alpha")
        for d in (src, rgbd, alpd):
            os.makedirs(d)
        sh([FFMPEG, "-v", "error", "-ss", f"{a.start}", "-t", f"{dur}", "-i", a.video,
            "-vf", f"fps={fps}", os.path.join(src, "s_%03d.png"), "-y"])
        frames = sorted(glob.glob(os.path.join(src, "s_*.png")))
        n = min(n, len(frames))
        if n < 3:
            raise SystemExit("segment too short")

        # ---- geometry: logo bbox from the middle of the segment.
        # Use row/column profiles so a stray spark cannot inflate the box.
        mid = np.array(Image.open(frames[len(frames) // 2]).convert("L")).astype(np.float32)
        m = mid > 45
        rows = np.where(m.sum(1) > max(4, 0.012 * m.shape[1]))[0]
        cols = np.where(m.sum(0) > max(4, 0.012 * m.shape[0]))[0]
        if len(rows) == 0 or len(cols) == 0:
            raise SystemExit("could not find the mark (frame is black); check --start/--end")
        by0, by1, bx0, bx1 = rows.min(), rows.max(), cols.min(), cols.max()
        logo_w, logo_h = bx1 - bx0, by1 - by0
        # thin tips (drops, tails) fade under the density threshold: allow for them
        by1 = min(H - 1, by1 + int(0.16 * logo_h))
        cx = (bx0 + bx1) / 2

        size = a.size
        if not size:                                  # text width ~= 95% of the mark
            ref = 200
            _, ref_w, _ = text_mask(a.text, font, ref, int(ref * 0.05), W, H, 0, cx)
            size = int(round(ref * (logo_w * 0.95) / max(ref_w, 1)))
            size = max(80, min(size, int(H * 0.42)))
        track = int(size * 0.05)
        _, tw, _ = text_mask(a.text, font, size, track, W, H, 0, cx)

        lay_probe = Image.new("L", (W, H), 0)
        ImageDraw.Draw(lay_probe).text((0, 0), a.text[0], font=ImageFont.truetype(font, size),
                                       fill=255, anchor="la")
        pbb = lay_probe.getbbox()
        ink_off_top, ink_off_bot = pbb[1], pbb[3]

        ink_top = int(by1 + a.gap)
        MASK, _, _ = text_mask(a.text, font, size, track, W, H, ink_top - ink_off_top, cx)
        ys2, xs2 = np.where(MASK > 0.3)
        ink_top, ink_bot = int(ys2.min()), int(ys2.max())
        if a.pinyin:
            pass
        print(f"mark {logo_w}x{logo_h} @x={cx:.0f}  text size={size} w={tw:.0f} "
              f"ink {ink_top}..{ink_bot}")

        # ---- text look
        stops = [(0.0, (1.00, 0.93, 1.00)), (0.20, (1.00, 0.74, 0.98)),
                 (0.55, (0.99, 0.44, 0.93)), (1.0, (0.58, 0.18, 0.82))]
        t = np.clip((np.arange(H, dtype=np.float32) - ink_top) / max(ink_bot - ink_top, 1), 0, 1) ** 1.05
        col = np.zeros((H, 3), np.float32)
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            m = (t >= p0) & (t <= p1)
            k = ((t - p0) / (p1 - p0))[m][:, None]
            col[m] = (1 - k) * np.array(c0, np.float32) + k * np.array(c1, np.float32)
        GRAD = np.repeat(col[:, None, :], W, axis=1)
        G1 = blur(MASK, 11)
        G2 = blur(MASK, 44)

        # ---- timing: appear once the mark is fully lit, leave with the source fade
        luma = []
        for p in frames[:n]:
            luma.append(np.array(Image.open(p).convert("L")).mean() / 255.0)
        peak = max(luma)
        formed = next((i for i, v in enumerate(luma) if v > 0.85 * peak), int(n * 0.35))
        fade_in = a.fade_in if a.fade_in is not None else max(0.0, formed / fps - 0.10)
        ramp = a.ramp
        out_start = dur - a.fade_out

        def shift(m, dy):
            if abs(dy) < 0.5:
                return m
            out = np.zeros_like(m)
            dy = int(round(dy))
            if dy > 0:
                out[dy:] = m[:-dy]
            else:
                out[:dy] = m[-dy:]
            return out

        for i, p in enumerate(frames[:n]):
            tt = i / fps
            r_in = ease((tt - fade_in) / ramp) if tt > fade_in else 0.0
            r_out = 1 - ease((tt - out_start) / max(a.fade_out, 1e-3))
            alpha = r_in * max(0.0, r_out)
            src_rgb = np.array(Image.open(p).convert("RGB")).astype(np.float32) / 255.0
            if alpha > 0.002:
                dy = 15 * (1 - r_in)
                m = shift(MASK, dy)
                a3 = (m * alpha)[..., None]
                src_rgb = src_rgb * (1 - a3) + GRAD * a3
                boost = 1.0 + 0.85 * (1 - r_in)
                src_rgb = src_rgb + np.array([1.0, 0.46, 0.92], np.float32)[None, None, :] * (
                    (shift(G1, dy) * 0.11 + shift(G2, dy) * 0.13) * alpha * boost)[..., None]
            src_rgb = np.clip(src_rgb, 0, 1)
            Image.fromarray((src_rgb * 255 + 0.5).astype(np.uint8)).save(
                os.path.join(rgbd, f"f_{i:03d}.png"))
            # straight-alpha version for WebM
            al = np.clip((src_rgb.max(2) - 0.040) / 0.90, 0, 1) ** 1.15
            al = blur(al, 0.7)
            straight = np.where(al[..., None] > 0.004,
                                np.clip(src_rgb / np.maximum(al[..., None], 1e-4), 0, 1), 0)
            Image.fromarray((np.dstack([straight, al]) * 255 + 0.5).astype(np.uint8)).save(
                os.path.join(alpd, f"f_{i:03d}.png"))

        mp4 = os.path.join(outdir, f"{name}.mp4")
        webm = os.path.join(outdir, f"{name}_alpha.webm")
        still = os.path.join(outdir, f"{name}_still.png")
        sh([FFMPEG, "-v", "error", "-framerate", str(fps), "-i", os.path.join(rgbd, "f_%03d.png"),
            "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", mp4, "-y"])
        sh([FFMPEG, "-v", "error", "-framerate", str(fps), "-i", os.path.join(alpd, "f_%03d.png"),
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "24",
            "-row-mt", "1", "-auto-alt-ref", "0", webm, "-y"])
        shutil.copy2(os.path.join(rgbd, f"f_{n // 2:03d}.png"), still)

    # ---- verify
    mi, wi = probe(mp4), probe(webm)
    mid_t = dur / 2
    chk = os.path.join(outdir, ".alpha_check.png")
    sh([FFMPEG, "-v", "error", "-c:v", "libvpx-vp9", "-ss", f"{mid_t}", "-i", webm,
        "-frames:v", "1", "-pix_fmt", "rgba", chk, "-y"])
    arr = np.array(Image.open(chk).convert("RGBA")).astype(np.float32) / 255.0
    os.remove(chk)
    print(f"mp4  {mi['w']}x{mi['h']} {mi['fps']:.0f}fps {mi['dur']:.2f}s "
          f"({os.path.getsize(mp4)/1e6:.2f} MB)")
    print(f"webm {wi['w']}x{wi['h']} {wi['fps']:.0f}fps {wi['dur']:.2f}s "
          f"({os.path.getsize(webm)/1e6:.2f} MB) alpha mean={arr[..., 3].mean():.3f} "
          f"corner={arr[0, 0, 3]:.2f}")
    if arr[..., 3].mean() < 0.005 or arr[0, 0, 3] > 0.5:
        print("WARNING: alpha looks wrong - decode with -c:v libvpx-vp9 when checking")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    an = sub.add_parser("analyze", help="find logo segments, write contact sheet")
    an.add_argument("--video", required=True)
    an.add_argument("--interval", type=float, default=2.5, help="seconds between sheet frames")
    an.add_argument("--dense", type=float, default=0.25, help="segmentation sampling step")
    an.add_argument("--out")
    an.set_defaults(func=cmd_analyze)

    bd = sub.add_parser("build", help="add the wordmark and encode")
    bd.add_argument("--video", required=True)
    bd.add_argument("--start", type=float, required=True)
    bd.add_argument("--end", type=float, required=True)
    bd.add_argument("--text", required=True)
    bd.add_argument("--font")
    bd.add_argument("--size", type=int, default=0, help="0 = auto (text width ~95%% of mark)")
    bd.add_argument("--gap", type=float, default=34, help="px between mark bottom and text top")
    bd.add_argument("--pinyin", default="", help="optional latin line (not implemented in v1)")
    bd.add_argument("--fps", type=int, default=0)
    bd.add_argument("--fade-in", type=float, default=None)
    bd.add_argument("--ramp", type=float, default=0.75)
    bd.add_argument("--fade-out", type=float, default=0.32)
    bd.add_argument("--outdir", default=".")
    bd.add_argument("--name", default="logo")
    bd.set_defaults(func=cmd_build)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
