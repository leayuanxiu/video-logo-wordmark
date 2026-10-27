#!/usr/bin/env python3
"""用用户的 logo 实际试排 7 种版式，输出一张对比图让对方点。

为什么要有这一步：版式问不出来。用户说"放好看就行"的时候，
给他看 7 张真实试排，比描述"下方居中 / 右侧横向 / 压字署名"有效得多。

用法：
  python layout_sheet.py --video in.mp4 --start 30.4 --end 33.4 --probe 31.5 \
      --out sheet.png --workdir .tmp
  # 可选：--text 莫辞  --num "2 2 0 8 0 1 8 0 8 0 5"
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.join(HERE, "make_wordmark.py")

LAYOUTS = [
    ("bottom", "下方居中", []),
    ("top", "上方居中", []),
    ("left", "左侧", []),
    ("right", "右侧横向", []),
    ("center", "嵌入中心", []),
    ("over_sign", "签名式压字", []),
    ("over_hero", "主标题压字", ["--rules-through"]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--probe", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--text", default=None)
    ap.add_argument("--num", default=None)
    ap.add_argument("--size-key", type=float, default=None)
    ap.add_argument("--cols", type=int, default=4)
    a = ap.parse_args()

    work = os.path.abspath(a.workdir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "_layout_tmp"))
    os.makedirs(work, exist_ok=True)

    imgs = []
    for key, label, extra in LAYOUTS:
        name = f"ls_{key}"
        cmd = [sys.executable, BUILDER,
               "--video", a.video, "--start", str(a.start), "--end", str(a.end),
               "--probe", str(a.probe), "--layout", key, "--still-only",
               "--name", name, "--outdir", work]
        if a.text:
            cmd += ["--text", a.text]
        if a.num:
            cmd += ["--num", a.num]
        if a.size_key:
            cmd += ["--size-key", str(a.size_key)]
        cmd += extra
        r = subprocess.run(cmd, capture_output=True, text=True)
        still = os.path.join(work, f"{name}_still.png")
        if r.returncode != 0 or not os.path.isfile(still):
            print(f"[skip] {key}: {(r.stderr or '').strip()[:160]}")
            continue
        imgs.append((key, label, still))

    if not imgs:
        if a.workdir is None:
            shutil.rmtree(work, ignore_errors=True)
        raise SystemExit("all layouts failed")

    cw, ch = 470, 264
    cols = a.cols
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw + 8, rows * (ch + 26) + 8), (8, 8, 10))
    d = ImageDraw.Draw(sheet)
    try:
        f1 = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 17)
    except OSError:
        f1 = ImageFont.load_default()
    for i, (key, label, p) in enumerate(imgs):
        c, r = i % cols, i // cols
        x, y = 4 + c * cw, 4 + r * (ch + 26)
        sheet.paste(Image.open(p).convert("RGB").resize((cw, ch), Image.LANCZOS), (x, y))
        d.text((x + 4, y + ch + 3), f"{i + 1}. {label}  ({key})",
               fill=(225, 230, 240), font=f1)
    sheet.save(a.out)

    if a.workdir is None:
        shutil.rmtree(work, ignore_errors=True)

    print(json.dumps([{"n": i + 1, "layout": k, "label": lb} for i, (k, lb, _) in enumerate(imgs)],
                     ensure_ascii=False))
    print(f"\nsheet -> {a.out}")
    print("把这张图给对方，问「第几个」。选定后再跑 make_wordmark.py 出片。")


if __name__ == "__main__":
    main()
