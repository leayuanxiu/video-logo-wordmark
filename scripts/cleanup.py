#!/usr/bin/env python3
"""扫出本流程可能留下的所有残留，默认只列不删。

为什么要有它：清理是最容易出事故的一步（用 -Include 误删过整个目录）。
所以这个脚本只认几种**明确的中间目录名**，默认 dry-run，必须自己加 --yes 才真删。

用法：
  python cleanup.py --dir "D:\\work"          # 只列
  python cleanup.py --dir "D:\\work" --yes    # 真删
  python cleanup.py --dir . --yes --temps     # 连系统 temp 里的抽帧一起清
"""
import argparse
import os
import shutil
import tempfile

# 只删这些名字的目录（本流程自己造的），别的一概不碰
DIR_PATTERNS = [
    "_layout_tmp", "_var_tmp", "_probe_tmp", "_scan_test",
    "chk", "frames_lotus",
]
DIR_PREFIXES = ["_src_", "_rgb_", "_alp_", "frames_"]
TEMP_PREFIXES = ["wm_", "scan_", "probe_"]

# 如果命中目录里出现这些扩展名，说明是人的东西，拒绝删除
KEEP_EXT = (".mp4", ".webm", ".mov", ".mkv")


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def dir_size(p):
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def has_media(p):
    for root, _, files in os.walk(p):
        for f in files:
            if f.lower().endswith(KEEP_EXT):
                return True
    return False


def collect(root, depth=3):
    hits = []
    root = os.path.abspath(root)
    for cur, dirs, _ in os.walk(root):
        rel = os.path.relpath(cur, root)
        if rel != "." and rel.count(os.sep) >= depth:
            dirs[:] = []
            continue
        for d in list(dirs):
            if d in DIR_PATTERNS or any(d.startswith(p) for p in DIR_PREFIXES):
                hits.append(os.path.join(cur, d))
                dirs.remove(d)
    return hits


def collect_temp():
    hits = []
    t = tempfile.gettempdir()
    try:
        for name in os.listdir(t):
            p = os.path.join(t, name)
            if os.path.isdir(p) and any(name.startswith(x) for x in TEMP_PREFIXES):
                hits.append(p)
    except OSError:
        pass
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".", help="要扫的项目目录")
    ap.add_argument("--yes", action="store_true", help="真的删；不加只列")
    ap.add_argument("--temps", action="store_true", help="连系统 temp 里的抽帧一起扫")
    a = ap.parse_args()

    hits = collect(a.dir)
    if a.temps:
        hits += collect_temp()

    if not hits:
        print("没有残留。")
        return

    total = 0
    doomed, kept = [], []
    for p in sorted(set(hits)):
        sz = dir_size(p)
        total += sz
        (kept if has_media(p) else doomed).append((p, sz))

    print(f"发现 {len(doomed) + len(kept)} 个中间目录，共 {human(total)}\n")
    for p, sz in doomed:
        print(f"  可删  {human(sz):>9}  {p}")
    for p, sz in kept:
        print(f"  跳过  {human(sz):>9}  {p}   (里面有视频文件，不敢动)")

    if not a.yes:
        print(f"\n这是 dry-run。确认后加 --yes 真删（{len(doomed)} 个）。")
        return

    freed = 0
    for p, sz in doomed:
        shutil.rmtree(p, ignore_errors=True)
        freed += sz
        print(f"  已删  {p}")
    print(f"\n释放 {human(freed)}。")


if __name__ == "__main__":
    main()
