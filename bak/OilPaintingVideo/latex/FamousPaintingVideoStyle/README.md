# OilPaintingRevive — IJCAI'26 Research Paper (Draft)

A research paper describing the **OilPaintingRevive** system: a five-stage
hybrid pipeline that brings famous oil paintings to life as 3D-explorable,
stylized videos via 2D Gaussian Splatting, skeleton binding, and LTX-Video
IC-LoRA diffusion.

The directory also retains the earlier **survey** paper as `main-survey.tex`.

## Directory Structure

```
FamousPaintingVideoStyle/
├── main.tex              # Research paper main file (IJCAI'26 template)
├── main-survey.tex       # Survey paper (backup, earlier version)
├── references.bib        # Bibliography (~50 entries)
├── ijcai26.sty           # IJCAI'26 style file
├── ijcai26.bib           # IJCAI'26 template bib
├── named.bst             # IJCAI recommended bibstyle
├── paper.pdf             # Compiled research paper (10 pages)
├── IMPROVEMENT_NOTES.md  # Improvement suggestions (Chinese)
└── sec/                  # Section files
    ├── intro.tex         # 1. Introduction
    ├── related.tex       # 2. Related Work
    ├── method.tex        # 3. Method (5 stages + screenplay pipeline)
    ├── experiment.tex    # 4. Experiments
    └── conclusion.tex    # 5. Conclusion
```

## Compilation

Compile with **XeLaTeX** (required for CJK support):

```bash
xelatex -jobname=paper main.tex
bibtex  paper
xelatex -jobname=paper main.tex
xelatex -jobname=paper main.tex
```

> `-jobname=paper` outputs `paper.pdf` to avoid conflicts if `main.pdf`
> (the survey) is open in a viewer. If no file is locked, you can omit
> `-jobname` and the output will be `main.pdf`.

To compile the **survey** instead:

```bash
xelatex -jobname=survey main-survey.tex
bibtex  survey
xelatex -jobname=survey main-survey.tex
xelatex -jobname=survey main-survey.tex
```

## Paper Structure

| Section | File | Content |
|---------|------|---------|
| Introduction | `sec/intro.tex` | Motivation, 3-role separation, 5 contributions |
| Related Work | `sec/related.tex` | Style transfer, diffusion video, Gaussian splatting, painting animation |
| Method | `sec/method.tex` | 5-stage pipeline + algorithm + screenplay pipeline |
| Experiments | `sec/experiment.tex` | Quantitative results, ablations, VRAM, user study |
| Conclusion | `sec/conclusion.tex` | Summary, limitations, future work |

## Source Code

The paper is based on two implemented projects:
- **OilPaintingRevive** (`D:\Code\AIforEducation\OilPaintingRevive`): single-painting 3D revival
- **OilPaintingVideo** (`D:\Code\AIforEducation\OilPaintingVideo`): screenplay-driven narrative short films
