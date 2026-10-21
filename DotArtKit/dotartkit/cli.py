"""cli.py — 统一命令行入口.

用法::

    # 列出所有模式
    python -m dotartkit.cli list

    # 用某模式生成
    python -m dotartkit.cli generate kusama_basic inputs/pumpkin.jpg -o outputs/out.png --palette yellow_black

    # 深度感知版 (需 polkadot-art 环境)
    python -m dotartkit.cli generate kusama_depth inputs/pumpkin.jpg -o outputs/depth.png --palette black_red

    # 跑 demo (全部纯 numpy 模式)
    python -m dotartkit.cli demo --input-dir inputs --output-dir outputs/demo

也可通过 ``dotart`` 脚本入口 (pyproject.toml 注册) 直接调用.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from PIL import Image

from .api import generate, list_modes, list_pure_modes, list_dl_modes, mode_info


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def _cmd_list(args: argparse.Namespace) -> int:
    """列出所有可用模式."""
    print("== 纯 numpy / scipy 模式 (无 DL 依赖) ==")
    for m in list_pure_modes():
        info = mode_info(m)
        print(f"  {m:14s}  {info['desc']}")
    print("\n== 深度学习模式 (需 ultralytics + YOLO26 权重) ==")
    for m in list_dl_modes():
        info = mode_info(m)
        deps = ", ".join(info["deps"]) or "(无)"
        print(f"  {m:14s}  {info['desc']}")
        print(f"                  依赖: {deps}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    """用指定模式生成一张图."""
    img = Image.open(args.input).convert("RGB")
    if args.long_edge and max(img.size) > args.long_edge:
        img.thumbnail((args.long_edge, args.long_edge))

    # 收集 kwargs: 仅传该模式接受的参数, 避免无关参数引发 TypeError.
    # 通用参数 (seed / long_edge 已在下采样处理) 对所有模式安全.
    # palette / n_points / r_max / alpha / sigma / overlap_gap / device 仅在
    # 对应模式有意义; 用 inspect 过滤.
    import inspect
    sig = inspect.signature(generate)
    accepted = set(sig.parameters.keys())
    # generate() 的签名是 (mode, image, **kwargs), 无法从签名知道具体流派参数.
    # 所以直接查目标流派的签名.
    from .api import MODES
    target_fn = MODES[args.mode]
    accepted = set(inspect.signature(target_fn).parameters.keys())

    candidate = {
        "palette": args.palette,
        "n_points": args.n_points,
        "r_max": args.r_max,
        "alpha": args.alpha,
        "sigma": args.sigma,
        "seed": args.seed,
        "overlap_gap": args.overlap_gap,
        "device": args.device,
        "target_long_edge": args.long_edge,
    }
    kwargs = {k: v for k, v in candidate.items() if v is not None and k in accepted}

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    t0 = time.time()
    out = generate(args.mode, img, **kwargs)
    out.save(args.output)
    print(f"[{args.mode}] {args.input} -> {args.output}  "
          f"({out.size[0]}x{out.size[1]}, {time.time()-t0:.2f}s)")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    """对所有纯 numpy 模式跑一遍 demo."""
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = sorted(input_dir.glob("*.jpg")) + sorted(input_dir.glob("*.png"))
    if not inputs:
        print(f"[demo] 未找到输入图: {input_dir}")
        return 1

    modes = list_pure_modes() if args.modes is None else args.modes.split(",")
    for inp in inputs:
        img = Image.open(inp).convert("RGB")
        img.thumbnail((480, 480))
        stem = inp.stem
        for mode in modes:
            t = time.time()
            try:
                out = generate(mode, img)
                out_path = output_dir / f"{stem}_{mode}.png"
                out.save(out_path)
                print(f"[{stem:10s}] {mode:14s} -> {out_path.name}  ({time.time()-t:5.2f}s)")
            except Exception as e:
                print(f"[{stem:10s}] {mode:14s} FAILED: {e}")
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dotart",
        description="DotArtKit — 统一波点艺术生成器 (8 流派)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # list
    sub.add_parser("list", help="列出所有可用模式")

    # generate
    g = sub.add_parser("generate", help="用指定模式生成一张图")
    g.add_argument("mode", help="模式键 (见 list)")
    g.add_argument("input", help="输入图像路径")
    g.add_argument("-o", "--output", default="output.png", help="输出路径")
    g.add_argument("--palette", default=None, help="调色板键 (kusama 系列)")
    g.add_argument("--n-points", type=int, default=None, help="点数")
    g.add_argument("--r-max", type=float, default=None, help="最大点半径")
    g.add_argument("--alpha", type=float, default=None, help="深度衰减指数 (kusama_depth)")
    g.add_argument("--sigma", type=float, default=None, help="半径噪声标准差")
    g.add_argument("--overlap-gap", type=float, default=None, help="点间距")
    g.add_argument("--seed", type=int, default=None, help="随机种子")
    g.add_argument("--device", default="0", help="GPU 编号或 cpu (DL 模式)")
    g.add_argument("--long-edge", type=int, default=None, help="下采样长边")
    g.set_defaults(func=_cmd_generate)

    # demo
    d = sub.add_parser("demo", help="对所有纯 numpy 模式跑 demo")
    d.add_argument("--input-dir", default="inputs", help="输入目录")
    d.add_argument("--output-dir", default="outputs/demo", help="输出目录")
    d.add_argument("--modes", default=None, help="逗号分隔的模式列表, 默认全部纯 numpy")
    d.set_defaults(func=_cmd_demo)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "list":
        return _cmd_list(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
