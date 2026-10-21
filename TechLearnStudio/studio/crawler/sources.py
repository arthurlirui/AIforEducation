"""ContentSource 抽象基类 + 各 adapter。

每个 adapter 负责抓取一种技术的文档/讲义，切分为 Section。
M5-M6 实现内置示例内容（离线可跑），真实抓取留接口。
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from composer import Section


@dataclass
class RawDoc:
    url: str = ""
    content: str = ""  # HTML/Markdown/纯文本


class ContentSource(ABC):
    """内容源抽象基类。"""
    kind: str = "base"
    subject: str = ""

    @abstractmethod
    def fetch(self) -> list[RawDoc]:
        """拉取原始文档。"""

    def fingerprint(self, docs: list[RawDoc]) -> str:
        """内容指纹（章节级 SHA-256）。"""
        raw = "".join(d.content for d in docs)
        return hashlib.sha256(raw.encode()).hexdigest()

    @abstractmethod
    def parse(self, docs: list[RawDoc]) -> list[Section]:
        """切分为语义小节。"""

    def get_sections(self) -> list[Section]:
        """便捷方法：fetch + parse。"""
        return self.parse(self.fetch())


# ---------- Python docs ----------
class PythonDocsSource(ContentSource):
    kind = "python_docs"
    subject = "python"

    def fetch(self) -> list[RawDoc]:
        # 离线内置示例（真实实现会抓 docs.python.org sitemap）
        return [
            RawDoc(url="docs.python.org/asyncio",
                   content="# asyncio 异步编程\n阻塞 IO 浪费线程。asyncio 用事件循环让单线程并发处理大量 IO。"),
        ]

    def parse(self, docs: list[RawDoc]) -> list[Section]:
        return [
            Section(
                title="Python 异步编程",
                body_md="阻塞 IO 会浪费线程。asyncio 用事件循环让单线程并发处理大量 IO。",
                code_blocks=[{"lang": "python", "src":
                    "import asyncio\nasync def hello():\n    await asyncio.sleep(0.1)\n    return 'hello'\nasyncio.run(hello())"}],
            ),
            Section(
                title="Python 装饰器",
                body_md="装饰器是一个函数，接收原函数返回新函数，用于横切关注点。",
                code_blocks=[{"lang": "python", "src":
                    "def log(func):\n    def wrap(*a, **kw):\n        print('call', func.__name__)\n        return func(*a, **kw)\n    return wrap\n\n@log\ndef hi():\n    print('hi')"}],
            ),
        ]


# ---------- Rust docs ----------
class RustDocsSource(ContentSource):
    kind = "rust_docs"
    subject = "rust"

    def fetch(self) -> list[RawDoc]:
        return [
            RawDoc(url="doc.rust-lang.org/book/ch04-ownership",
                   content="# 所有权\nRust 用单一所有权 + 编译期检查，消除悬垂指针与双重释放。"),
        ]

    def parse(self, docs: list[RawDoc]) -> list[Section]:
        return [
            Section(
                title="Rust 所有权",
                body_md="Rust 用单一所有权 + 编译期检查，消除悬垂指针与双重释放。",
                code_blocks=[{"lang": "rust", "src":
                    'fn main() {\n    let s = String::from("hi");\n    let t = s;  // move\n    println!("{}", t);\n}'}],
                anim_kind="ownership_move",
            ),
            Section(
                title="Rust 借用与引用",
                body_md="借用让函数访问数据而不获取所有权。不可变引用 &T 和可变引用 &mut T。",
                code_blocks=[{"lang": "rust", "src":
                    "fn len(s: &String) -> usize { s.len() }\nfn main() {\n    let s = String::from(\"hello\");\n    println!(\"{}\", len(&s));\n}"}],
            ),
        ]


# ---------- Go docs ----------
class GoDocsSource(ContentSource):
    kind = "go_docs"
    subject = "go"

    def fetch(self) -> list[RawDoc]:
        return [
            RawDoc(url="go.dev/doc/effective_go",
                   content="# Go 并发\ngoroutine 是轻量级线程，channel 用于 goroutine 间通信。"),
        ]

    def parse(self, docs: list[RawDoc]) -> list[Section]:
        return [
            Section(
                title="Go 并发：goroutine 与 channel",
                body_md="goroutine 是轻量级线程（~2KB 栈），channel 用于 goroutine 间安全通信。不要通过共享内存通信，而通过通信共享内存。",
                code_blocks=[{"lang": "go", "src":
                    'package main\nimport "fmt"\nfunc main() {\n    ch := make(chan int)\n    go func() { ch <- 42 }()\n    fmt.Println(<-ch)\n}'}],
            ),
            Section(
                title="Go 接口",
                body_md="Go 接口是隐式实现：只要类型实现了接口的所有方法，就自动满足该接口。",
                code_blocks=[{"lang": "go", "src":
                    "package main\nimport \"fmt\"\ntype Speaker interface { Speak() string }\ntype Dog struct{}\nfunc (d Dog) Speak() string { return \"Woof\" }\nfunc main() { var s Speaker = Dog{}; fmt.Println(s.Speak()) }"}],
            ),
        ]


# ---------- TypeScript docs ----------
class TSDocsSource(ContentSource):
    kind = "ts_docs"
    subject = "typescript"

    def fetch(self) -> list[RawDoc]:
        return [
            RawDoc(url="typescriptlang.org/docs/handbook/types",
                   content="# TypeScript 类型系统\nTypeScript 在 JavaScript 上添加静态类型，编译时检查。"),
        ]

    def parse(self, docs: list[RawDoc]) -> list[Section]:
        return [
            Section(
                title="TypeScript 类型系统",
                body_md="TypeScript 在 JavaScript 上添加静态类型，编译时检查类型错误，提升代码可维护性。",
                code_blocks=[{"lang": "typescript", "src":
                    "function greet(name: string): string {\n    return `Hello, ${name}!`;\n}\nconsole.log(greet('World'));"}],
            ),
            Section(
                title="TypeScript 泛型",
                body_md="泛型让函数和类型可复用于多种类型，同时保持类型安全。",
                code_blocks=[{"lang": "typescript", "src":
                    "function identity<T>(value: T): T {\n    return value;\n}\nconst n: number = identity(42);\nconst s: string = identity('hi');"}],
            ),
        ]


# ---------- 信号与系统 ----------
class SignalSystemSource(ContentSource):
    kind = "course_signal"
    subject = "signal-system"

    def fetch(self) -> list[RawDoc]:
        return [
            RawDoc(url="local://信号与系统讲义/卷积",
                   content="# 卷积\n卷积描述信号经过线性时不变系统后的输出。"),
            RawDoc(url="local://信号与系统讲义/傅里叶",
                   content="# 傅里叶变换\n将时域信号分解为频域正弦分量的叠加。"),
        ]

    def parse(self, docs: list[RawDoc]) -> list[Section]:
        return [
            Section(
                title="信号卷积",
                body_md="卷积描述一个信号经过线性时不变系统后的输出。",
                formula=r"y[n] = \sum_{k=-\infty}^{\infty} x[k]\, h[n-k]",
                code_blocks=[{"lang": "python", "src":
                    "import numpy as np\nx = np.array([1, 2, 3])\nh = np.array([1, 0, -1])\nprint(np.convolve(x, h))"}],
                anim_kind="convolution",
            ),
            Section(
                title="傅里叶变换",
                body_md="傅里叶变换将时域信号分解为频域正弦分量的叠加，是信号处理的核心工具。",
                formula=r"X(f) = \int_{-\infty}^{\infty} x(t)\, e^{-j2\pi ft}\, dt",
                code_blocks=[{"lang": "python", "src":
                    "import numpy as np\nx = np.array([1, 0, -1, 0])\nX = np.fft.fft(x)\nprint(np.abs(X))"}],
            ),
        ]


# ---------- 无线通信 ----------
class WirelessSource(ContentSource):
    kind = "course_wireless"
    subject = "wireless"

    def fetch(self) -> list[RawDoc]:
        return [
            RawDoc(url="local://无线通信讲义/OFDM",
                   content="# OFDM\n正交频分复用将高速数据流分配到多个正交子载波上。"),
            RawDoc(url="local://无线通信讲义/信道",
                   content="# 无线信道\n多径效应导致信号衰落，信道模型描述信号传播特性。"),
        ]

    def parse(self, docs: list[RawDoc]) -> list[Section]:
        return [
            Section(
                title="OFDM 原理",
                body_md="正交频分复用将高速数据流分配到多个正交子载波上，每个子载波承载低速数据，有效对抗频率选择性衰落。",
                formula=r"s(t) = \sum_{k=0}^{N-1} X_k\, e^{j2\pi f_k t}",
                code_blocks=[{"lang": "python", "src":
                    "import numpy as np\nN = 4\nX = np.array([1, -1, 1, -1])\ns = np.fft.ifft(X)\nprint(np.round(np.abs(s), 3))"}],
                anim_kind="ofdm_subcarriers",
            ),
            Section(
                title="无线信道模型",
                body_md="多径效应导致信号经不同路径到达接收端，产生时延扩展和衰落。信道冲激响应描述这一特性。",
                formula=r"h(t) = \sum_{i} \\alpha_i\, \\delta(t - \\tau_i)",
                code_blocks=[{"lang": "python", "src":
                    "import numpy as np\n# 多径信道：3条路径，不同时延和增益\npaths = [(0, 1.0), (3, 0.5), (6, 0.2)]\nh = np.zeros(10)\nfor delay, gain in paths:\n    h[delay] = gain\nprint(h)"}],
            ),
        ]


# ---------- 大模型 ----------
class LLMSource(ContentSource):
    kind = "course_llm"
    subject = "llm"

    def fetch(self) -> list[RawDoc]:
        return [
            RawDoc(url="local://大模型讲义/注意力",
                   content="# 注意力机制\n注意力机制让模型动态关注输入的不同部分。"),
            RawDoc(url="local://大模型讲义/Transformer",
                   content="# Transformer 架构\nTransformer 用自注意力替代循环，支持并行训练。"),
        ]

    def parse(self, docs: list[RawDoc]) -> list[Section]:
        return [
            Section(
                title="注意力机制",
                body_md="注意力机制让模型动态关注输入的不同部分，通过 query-key-value 三元组计算权重。",
                formula=r"\text{Attention}(Q,K,V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V",
                code_blocks=[{"lang": "python", "src":
                    "import numpy as np\nQ = np.random.randn(4, 8)\nK = np.random.randn(4, 8)\nscores = Q @ K.T / np.sqrt(8)\nweights = np.exp(scores) / np.exp(scores).sum(-1, keepdims=True)\nprint(np.round(weights, 3))"}],
                anim_kind="attention_flow",
            ),
            Section(
                title="Transformer 架构",
                body_md="Transformer 用自注意力替代循环结构，支持并行训练。多头注意力让模型在不同子空间学习不同模式。",
                code_blocks=[{"lang": "python", "src":
                    "# 简化的多头注意力\nimport numpy as np\ndef multi_head_attention(Q, K, V, n_heads=2):\n    # split → attention → concat → linear\n    d = Q.shape[-1] // n_heads\n    heads = []\n    for i in range(n_heads):\n        q, k, v = Q[:, i*d:(i+1)*d], K[:, i*d:(i+1)*d], V[:, i*d:(i+1)*d]\n        scores = q @ k.T / np.sqrt(d)\n        attn = np.exp(scores) / np.exp(scores).sum(-1, keepdims=True)\n        heads.append(attn @ v)\n    return np.concatenate(heads, -1)\nprint('ok')"}],
            ),
        ]


# ---------- 注册表 ----------
REGISTRY: dict[str, type[ContentSource]] = {
    "python_docs": PythonDocsSource,
    "rust_docs": RustDocsSource,
    "go_docs": GoDocsSource,
    "ts_docs": TSDocsSource,
    "course_signal": SignalSystemSource,
    "course_wireless": WirelessSource,
    "course_llm": LLMSource,
}


def get_source(source_id: str) -> ContentSource | None:
    cls = REGISTRY.get(source_id)
    return cls() if cls else None


def list_sources() -> list[dict]:
    return [{"id": sid, "kind": cls.kind, "subject": cls.subject} for sid, cls in REGISTRY.items()]
