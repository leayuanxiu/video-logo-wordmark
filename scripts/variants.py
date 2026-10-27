#!/usr/bin/env python3
"""对单个参数出三档变体，让用户点选。

用户说不清"哪里不对"的时候，别问开放式问题——出三张图，问"哪张"。
比让他描述"字有点大但又说不上太大"有效得多。

用法：
  # 字号三档
  python variants.py --video in.mp4 --start 30.4 --end 33.4 --probe 31.5 \
      --param size-key --values 0.58,0.70,0.82 --out size.png

  # 间距三档
  python variants.py ... --param gap --values 20,46,80 --out gap.png

  # 色相三档
  python variants.py ... --param hue --values 266,320,45 --out hue.png

  # 固定其它参数
  python variants.py ... --param edge-sep --values 0.45,0.65,0.85 \
      --extra "--layout over_hero --rules-through"
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

# 每个参数配一句"这个值意味着什么"，直接印在图上，用户看得懂
HINTS = {
    "size-key": "字号（越大字越占地方）",
    "gap": "标志到字的间距 px",
    "hue": "色相 0-360（266紫 / 320粉 / 45金 / 200青）",
    "sat": "饱和度（0 灰白 / 1 浓）",
    "track": "字距（越大越开）",
    "edge-sep": "字外暗环强度（越大分得越开）",
    "text-in": "字开始淡入的秒数",
    "ramp": "淡入时长（秒）",
    "text-out": "字开始淡出的秒数",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--probe", type=float, required=True)
    ap.add_argument("--param", required=True, help="要扫的参数，如 size-key / gap / hue")
    ap.add_argument("--values", required=True, help="逗号分隔，如 0.58,0.70,0.82")
    ap.add_argument("--out", required=True)
    ap.add_argument("--layout", default="bottom")
    ap.add_argument("--text", default=None)
    ap.add_argument("--num", default=None)
    ap.add_argument("--extra", default="", help="固定附加参数，如 '--rules-through'")
    ap.add_argument("--workdir", default=None)
    a = ap.parse_args()

    vals = [v.strip() for v in a.values.split(",") if v.strip()]
    if not 1 <= len(vals) <= 4:
        raise SystemExit("--values 给 1-4 个")

    work = os.path.abspath(a.workdir or os.path.join(
        os.path.dirname(os.path.abspath(a.out)), "_var_tmp"))
    os.makedirs(work, exist_ok=True)

    imgs = []
    for i, v in enumerate(vals):
        name = f"v{i}"
        cmd = [sys.executable, BUILDER,
               "--video", a.video, "--start", str(a.start), "--end", str(a.end),
               "--probe", str(a.probe), "--layout", a.layout, "--still-only",
               "--name", name, "--outdir", work,
               f"--{a.param}", v]
        if a.text:
            cmd += ["--text", a.text]
        if a.num:
            cmd += ["--num", a.num]
        if a.extra:
            cmd += a.extra.split()
        r = subprocess.run(cmd, capture_output=True, text=True)
        still = os.path.join(work, f"{name}_still.png")
        if r.returncode != 0 or not os.path.isfile(still):
            print(f"[skip] {v}: {(r.stderr or '').strip()[:140]}")
            continue
        info = {}
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    info = json.loads(line)
                except ValueError:
                    pass
        imgs.append((v, still, bool(info.get("capped"))))

    if not imgs:
        if a.workdir is None:
            shutil.rmtree(work, ignore_errors=True)
        raise SystemExit("all variants failed")

    cw, ch = 640, 360
    n = len(imgs)
    sheet = Image.new("RGB", (n * cw + 8, ch + 56), (8, 8, 10))
    d = ImageDraw.Draw(sheet)
    try:
        f1 = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 20)
        f2 = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 15)
    except OSError:
        f1 = f2 = ImageFont.load_default()
    hint = HINTS.get(a.param, a.param)
    for i, (v, p, capped) in enumerate(imgs):
        x = 4 + i * cw
        sheet.paste(Image.open(p).convert("RGB").resize((cw, ch), Image.LANCZOS), (x, 4))
        tag = f"{i + 1}.  --{a.param} {v}" + ("  [已封顶，再调不动]" if capped else "")
        d.text((x + 4, ch + 8), tag, fill=(255, 160, 80) if capped else (255, 215, 60), font=f1)
        d.text((x + 4, ch + 32), f"    {hint}", fill=(150, 195, 235), font=f2)
    sheet.save(a.out)

    if a.workdir is None:
        shutil.rmtree(work, ignore_errors=True)

    print(json.dumps([{"n": i + 1, "value": v, "capped": c} for i, (v, _, c) in enumerate(imgs)],
                     ensure_ascii=False))
    print(f"\nsheet -> {a.out}")
    print("问用户「第几个」，别问「你觉得哪里不对」。")


if __name__ == "__main__":
    main()
