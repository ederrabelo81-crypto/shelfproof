"""Folha de contato: todas as pecas com imagem numa unica figura, para a revisao humana.

E aqui que se decide o que NAO vai para o Showroom publicado (celebridade,
pessoa real, peca quebrada). O nome de cada miniatura e o mesmo usado em
``review.json`` (``<site>_<nn>``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from PIL import Image, ImageDraw


def contact_sheet(showroom_dir: Path, out_file: Path, width: int = 1600) -> Path:
    data = json.loads((Path(showroom_dir) / "data.json").read_text(encoding="utf-8"))["data"]
    tiles: List[tuple] = []
    for p in data["pieces"]:
        im = Image.open(Path(showroom_dir) / "img" / f"{p['img']}.webp").convert("RGB")
        s = 220 / im.height if im.width / im.height < 2.2 else 520 / im.width
        tiles.append((f"{p['img']}  [{p['k']}] {p['adv']}", im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))))
    x = y = rowh = 0
    pos = []
    for label, t in tiles:
        if x + t.width > width:
            x, y, rowh = 0, y + rowh + 26, 0
        pos.append((x, y, label, t))
        x += t.width + 10
        rowh = max(rowh, t.height)
    sheet = Image.new("RGB", (width, y + rowh + 30), "white")
    d = ImageDraw.Draw(sheet)
    for x, y, label, t in pos:
        sheet.paste(t, (x, y + 22))
        d.text((x, y + 4), label, fill="red")
    sheet.save(out_file, quality=75)
    return out_file
