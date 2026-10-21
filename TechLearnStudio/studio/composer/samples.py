"""内置示例内容：用 Section 描述几节真实课程，供 Studio compose 与测试使用。"""
from __future__ import annotations

from . import Section


PYTHON_ASYNCIO = Section(
    title="Python 异步编程",
    body_md="阻塞 IO 会浪费线程。asyncio 用事件循环让单线程并发处理大量 IO。",
    code_blocks=[{
        "lang": "python",
        "src": "import asyncio\n\nasync def hello():\n    await asyncio.sleep(0.1)\n    return 'hello'\n\nasyncio.run(hello())",
    }],
)

SIGNAL_CONVOLUTION = Section(
    title="信号卷积",
    body_md="卷积描述一个信号经过线性时不变系统后的输出。",
    formula=r"y[n] = \sum_{k=-\infty}^{\infty} x[k]\, h[n-k]",
    code_blocks=[{
        "lang": "python",
        "src": "import numpy as np\nx = np.array([1, 2, 3])\nh = np.array([1, 0, -1])\nprint(np.convolve(x, h))",
    }],
    anim_kind="convolution",
)

RUST_OWNERSHIP = Section(
    title="Rust 所有权",
    body_md="Rust 用单一所有权 + 编译期检查，消除悬垂指针与双重释放。",
    code_blocks=[{
        "lang": "rust",
        "src": 'fn main() {\n    let s = String::from("hi");\n    let t = s;  // move\n    println!("{}", t);\n}',
    }],
    anim_kind="ownership_move",
)

SAMPLES = {
    "python-asyncio": ("Python 异步编程", "language", "python", PYTHON_ASYNCIO),
    "signal-convolution": ("信号卷积", "course", "signal-system", SIGNAL_CONVOLUTION),
    "rust-ownership": ("Rust 所有权", "language", "rust", RUST_OWNERSHIP),
}
