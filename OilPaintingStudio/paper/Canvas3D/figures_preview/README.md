# Canvas3D Draw.io Figure Variants

This directory contains the same 15 figure variants (5 figures x 3 styles)
in Draw.io XML format. You can open them at [draw.io](https://app.diagrams.net)
for further editing.

## Style Legend

- **Variant A (Flat Modern)**: Solid color fills, rounded corners, sans-serif, high contrast. Best for presentations.
- **Variant B (Minimal Mono)**: Black outlines only, no fills, thin strokes, white background. Best for B/W printing.
- **Variant C (Academic Accent)**: Light gray fills with blue accent on novel/key modules, rounded corners. Best for paper submission.

## File Naming

`figX_modulename_variantY.drawio`

- X = 1..5 (overview, paintparse, monosplat, sketchcomp, artiflow)
- Y = A, B, or C

## Color Palette (Variant A)

| Module | Color | Hex |
|--------|-------|-----|
| PaintParse | Blue | #1976D2 |
| MonoSplat | Teal | #009688 |
| SketchComp | Orange | #F57C00 |
| ArtiFlow | Red | #D32F2F |
| Data/Input | Light yellow | #FFF9C4 |
| Library | Purple | #7B1FA2 |

## Usage in LaTeX

After choosing a variant, replace the corresponding `\begin{figure}...\end{figure}`
block in `sec/method.tex` with the selected variant's TikZ code. The code is
already wrapped in `\resizebox{\linewidth}{!}{...}` to prevent overfull boxes.
