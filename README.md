# HatchSmith

HatchSmith converts a PNG into **separate color layers** and **plotter-friendly hatch-filled SVGs** so regions look “filled” using real strokes.

Most pen plotters (and many mural robots) don’t render SVG `fill`. They follow paths. HatchSmith generates hatch strokes inside regions so your machine can draw filled-looking areas on walls, canvases, and large-format layouts.

**© FIWAtec GmbH**

---

## GitHub “About” (copy/paste)

PNG → color layers + hatch-filled SVGs for pen plotters. Exports transparent PNG layers and plotter-ready hatch strokes so filled regions are drawn as real lines.

---

## Table of contents

- [What it does](#what-it-does)
- [Why hatch fill](#why-hatch-fill)
- [Key features](#key-features)
- [Requirements](#requirements)
- [Install & run](#install--run)
- [Typical workflow](#typical-workflow)
- [Parameters that matter](#parameters-that-matter)
- [Custom label/order list](#custom-labelorder-list)
- [Output structure](#output-structure)
- [Tips for plotters](#tips-for-plotters)
- [Performance notes](#performance-notes)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [License](#license)

---

## What it does

Given a PNG input, HatchSmith can export:

- **Quantized preview PNG** (reduced to *N* dominant colors)
- **PNG color layers** (one transparent PNG per color)
- **SVG hatch layers** (one SVG per color, filled via hatch strokes)
- **Combined SVG** (all layers merged in one SVG)
- **Layer mapping + stats** (palette list, coverage, path counts)

---

## Why hatch fill

Pen plotters and mural robots typically ignore SVG fills and only draw strokes.

If you want a filled look, the machine needs many strokes inside the region. HatchSmith builds hatch patterns:

- Darker tones → **denser** hatching (optional crosshatch)
- Lighter tones → **sparser** hatching

Result: the plotter draws real strokes that visually read as filled areas.

---

## Key features

- PNG preview with mouse-wheel zoom
- Color quantization (2–64 colors)
- Transparent PNG layers per color
- Hatch-filled SVG export (per layer + combined)
- Adjustable **target size (mm)** and **pen width (mm)** for correct hatch density
- Optional **custom label/order list** for stable naming and paint order
- Non-blocking export (UI stays responsive)
- Progress bar + activity log
- Dark UI

---

## Requirements

- Python 3.10+
- Packages:
  - PySide6
  - Pillow
  - numpy

If `pip` is available, HatchSmith can auto-install missing packages on first run.

---

## Install & run

### Option A: install dependencies manually

```bash
pip install -U PySide6 Pillow numpy
python hatchSmithmain.py
