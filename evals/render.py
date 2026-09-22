"""Draw the layout and spot diagram for an exported lens.

python evals/render.py out/achromat_100-0/638b8974.json        -> writes .layout.png and .spot.png beside it
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from optiland.analysis import SpotDiagram  # noqa: E402
from optiland.fileio import load_optiland_file  # noqa: E402


def render(path: str) -> tuple[Path, Path]:
    p = Path(path)
    lens = load_optiland_file(str(p))
    fig, ax = lens.draw(num_rays=5, figsize=(9, 3.4), show=False)
    ax.set_title("")
    layout = p.with_suffix(".layout.png")
    fig.savefig(layout, dpi=110, bbox_inches="tight")
    plt.close(fig)
    fig, _ = SpotDiagram(lens).view(figsize=(9, 3.2), show=False)
    spot = p.with_suffix(".spot.png")
    fig.savefig(spot, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return layout, spot


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(*render(arg))
