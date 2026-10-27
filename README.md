# video-logo-wordmark

把视频里现成的动态 logo 取出来，加上自己的中文字标，输出 **MP4 + 透明背景 WebM**。原动画一帧不改。

> Take an animated logo out of a video (logo montage, brand bumper, logo reveal) and stamp a Chinese wordmark onto it — without re-animating the original. Outputs MP4 + transparent WebM.

给需要「一个能动的 logo，但自己不会做动画」的人：素材是别人的，字是你的。

---

## 它能做什么

- **从多 logo 合集里定位**：逐帧扫亮度切段，出带编号的对照图让人点
- **配色跟随标志**：从标志亮部取主色相，字的渐变、光晕、细线全跟着变（金标志出金字，银标志出银字）
- **7 种版式**：下方 / 上方 / 左侧 / 右侧 / 嵌入中心 / 签名式压字 / 主标题压字
- **同色压字不糊**：字外一圈暗环 + 边缘柔暗，让同色字和标志分得开
- **字体和线条处理**：行楷字标、两侧细线、穿字横线、数字串副标
- **先静帧后编码**：5 秒出静帧让你确认，点头了才花 2–4 分钟跑全片
- **返修给选择题**：不说"哪里不对"，出三档图让你点
- **清理不留垃圾**：专用清理脚本，默认 dry-run，有视频文件就拒绝删

## 前置

| 依赖 | 说明 |
|---|---|
| Windows | 字体路径按 Windows 写死（`C:\Windows\Fonts`、`%LOCALAPPDATA%\...\Fonts`） |
| Python 3.10+ | 需要 `Pillow`、`numpy` |
| ffmpeg / ffprobe | 必须在 PATH 里 |

```bash
pip install pillow numpy
ffmpeg -version   # 确认可用
```

## 安装

这个 skill 靠 agent 的 skill 目录约定被识别，克隆到那里：

```bash
git clone https://github.com/leayuanxiu/video-logo-wordmark.git \
  ~/.agents/skills/video-logo-wordmark
```

Windows（PowerShell）：

```powershell
git clone https://github.com/leayuanxiu/video-logo-wordmark.git `
  "$env:USERPROFILE\.agents\skills\video-logo-wordmark"
```

不用装成 Python 包，脚本按路径直接跑：

```bash
python ~/.agents/skills/video-logo-wordmark/scripts/scan_segments.py --help
```

只想临时用的话，clone 到任何目录都行，把命令里的路径换掉即可——但 agent 要自动发现这个 skill，就必须在 `~/.agents/skills/` 下。

**国内网络注意**：如果 `github.com` 直连超时但浏览器能开，说明系统代理只对浏览器生效。git 需要显式指定：

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:7897"   # 换成你自己的代理端口
git clone ...
```

## 快速开始

```bash
# 1. 扫全片，拿到候选段 + 缩略图
python scripts/scan_segments.py --video input.mp4 --out segs.png

# 2. 定区间（图上点编号，再确认秒级范围）

# 3. 核成形帧，挑"最完整"的那一帧
python scripts/probe_strip.py --video input.mp4 --start 30.4 --end 33.4 --out probe.png

# 4. 看 7 种版式实拍对比
python scripts/layout_sheet.py --video input.mp4 --start 30.4 --end 33.4 \
    --probe 31.5 --out sheet.png

# 5. 先出静帧（5 秒）
python scripts/make_wordmark.py --video input.mp4 --start 30.4 --end 33.4 \
    --probe 31.5 --text "\u83ab\u8f9e" --layout bottom --still-only \
    --name my_logo --outdir out

# 6. 确认后出全片（去掉 --still-only）
python scripts/make_wordmark.py --video input.mp4 --start 30.4 --end 33.4 \
    --probe 31.5 --text "\u83ab\u8f9e" --layout bottom \
    --name my_logo --outdir out
```

产出：`my_logo.mp4`、`my_logo_alpha.webm`、`my_logo_still.png`。

> Windows 终端可能把中文参数转码，`--text "\u83ab\u8f9e"` 这种转义最稳。

## 流水线

```
1 扫全片  →  2 定区间  →  3 核成形帧  →  4 选版式
                                             ↓
8 清理  ←  7 交付  ←  6 全片  ←  5 静帧
```

**四个必须停下等人点头的地方**：定区间、选版式、看静帧、确认满意。

## 脚本

| 脚本 | 干什么 |
|---|---|
| `scan_segments.py` | 拿到新视频第一步：逐帧扫全片，出段表 + 缩略图 |
| `probe_strip.py` | 给区间抽 6 帧，挑"最完整"的那帧当 `--probe` |
| `layout_sheet.py` | 用目标 logo 实拍 7 种版式，出对比图 |
| `variants.py` | 返修用：单个参数出 3 档，让用户点"第几个" |
| `make_wordmark.py` | 出片：配色 + 版式 + 线条 + 编码 |
| `cleanup.py` | 扫残留，默认只列不删 |
| `make_logo.py` | 早期版本，只剩 `analyze` 兜底 |

完整说明见 [`SKILL.md`](SKILL.md) —— 12 节，含流水线、版式规则、配色公式、坑清单、返修对照表。

## 几个反直觉的设计决定

- **字宽按墨迹反解，不按字体 advance**：行楷的 advance 比墨迹宽一倍，按 advance 定字号出来只有想要的一半。
- **字高封顶 `0.66 × 标志高`**：扁宽标志若只按宽度定字号，字会高过标志、抢主体并顶到底边。撞上限时图上会标 `[已封顶，再调不动]`。
- **bbox 用亮部阈值 0.35，不用 45/255**：暗部辉光会把 bbox 撑大 30%，字就按虚边算了。
- **不用描边（stroke）分离同色字**：发光线稿上加硬边描边像贴纸。用暗环 + 柔暗底，字才像"浮在光里"。
- **分段结果只当候选**：亮度阈值分不清"两个 logo 之间的黑"和"同一 logo 内部的暗"，永远要人收一遍。

## 已知限制

- **Windows 专用**：字体路径硬编码，换平台要改 `FONT_CANDIDATES` / `LAT_CANDIDATES`。
- **透明 WebM 要求背景纯黑**：给画面加波形、网格、渐变底会让 alpha 版失去意义。
- **竖版 1080×1920 未内置**：需要自己 pad/crop 重排。
- **切点依赖源素材**：源动画没有淡出的话，结尾只能硬切。
- **编码耗时**：1080p / 4–6 秒约 2–4 分钟；10 秒以上 VP9 要 5–8 分钟。

## License

MIT
