"""Small local glyph reader for the game's percentage text (no OCR service)."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def normalize(mask):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    cut = mask[ys.min():ys.max()+1, xs.min():xs.max()+1]
    return np.asarray(Image.fromarray(cut.astype('uint8')*255).resize((24, 36), Image.Resampling.BILINEAR)) > 100


def split_glyph_groups(mask):
    """Split percentage glyphs using projection valleys, not only blank columns.

    The game font can render the final digit and percent sign one pixel apart
    (or anti-aliased into touching columns).  A pure blank-column splitter then
    merges them, e.g. 35% becomes 3%.
    """
    projection = mask.sum(axis=0)
    cols = np.flatnonzero(projection > 0)
    if len(cols) == 0:
        return []
    runs = np.split(cols, np.flatnonzero(np.diff(cols) > 1) + 1)
    runs = [(int(run[0]), int(run[-1])) for run in runs if len(run)]
    ys = np.flatnonzero(mask.sum(axis=1) > 0)
    glyph_height = int(ys[-1] - ys[0] + 1) if len(ys) else mask.shape[0]

    result = []
    for x0, x1 in runs:
        width = x1 - x0 + 1
        # A normal percent sign is wider than a digit, so only split a run when
        # it is wider than a plausible single glyph.  Then cut at the weakest
        # vertical projection valley with enough pixels on both sides.
        if width > max(18, glyph_height * 1.45):
            margin = max(4, int(glyph_height * .30))
            lo, hi = x0 + margin, x1 - margin
            if hi >= lo:
                values = projection[lo:hi + 1]
                minimum = values.min()
                if minimum <= max(3, int(projection[x0:x1 + 1].max() * .35)):
                    candidates = np.flatnonzero(values == minimum) + lo
                    preferred = x0 + int(glyph_height * .65)
                    split = int(candidates[np.argmin(np.abs(candidates - preferred))])
                    result.append((x0, split - 1))
                    result.append((split + 1, x1))
                    continue
        result.append((x0, x1))
    return result


class PercentageReader:
    def __init__(self):
        self.templates = []
        for name in ('arialbd.ttf', 'segoeuib.ttf', 'arial.ttf', 'verdanab.ttf', 'tahomabd.ttf', 'trebucbd.ttf', 'consolab.ttf'):
            path = Path('C:/Windows/Fonts') / name
            if not path.exists():
                continue
            for size in (20, 32, 48):
                font = ImageFont.truetype(str(path), size)
                for ch in '0123456789%':
                    im = Image.new('L', (100, 100))
                    ImageDraw.Draw(im).text((5, 5), ch, font=font, fill=255)
                    mask = np.asarray(im) > 110
                    ys, xs = np.nonzero(mask)
                    self.templates.append((ch, normalize(mask), (xs.max()-xs.min()+1)/(ys.max()-ys.min()+1)))
        self.template_masks = np.stack([item[1] for item in self.templates])
        self.template_ratios = np.asarray([item[2] for item in self.templates])

    def read(self, image):
        a = np.asarray(image.convert('RGB')).astype(np.int16)
        r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        spread = a.max(axis=2) - a.min(axis=2)

        # Real screenshots show red/pink text at low progress and pale/white
        # text later in the catch.  Keep three passes so background pixels in a
        # tight selection do not overpower the glyph shapes.
        red = (r > 100) & ((r - g) > 8) & ((r - b) > 5)
        pink = (r > 145) & (g > 95) & (b > 95) & (r >= g) & (r >= b) & ((r - b) > 5)
        white = (a.min(axis=2) > 145) & (spread < 110)

        for mask in (red | pink, white, red | pink | white):
            groups = split_glyph_groups(mask)
            groups = [(x0, x1) for x0, x1 in groups if x1 - x0 + 1 >= 2]
            if not 2 <= len(groups) <= 4:
                continue

            text = ''
            valid = True
            for x0, x1 in groups:
                cut = mask[:, x0:x1 + 1]
                ys, xs = np.nonzero(cut)
                if len(ys) < 5 or ys.max() - ys.min() < 6:
                    valid = False
                    break
                ratio = (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
                norm = normalize(cut)
                comparisons = np.logical_xor(norm, self.template_masks).mean(axis=(1, 2))
                comparisons += np.minimum(.3, np.abs(ratio - self.template_ratios) * .16)
                best = comparisons.reshape(-1, 11).min(axis=0)
                scores = dict(zip('0123456789%', best))
                ranked = sorted(scores, key=scores.get)
                # Slightly more tolerant than the synthetic-font-only version;
                # the game applies outlines, shadows, scaling, and transparency.
                if scores[ranked[0]] > .32 or scores[ranked[1]] - scores[ranked[0]] < .006:
                    valid = False
                    break
                text += ranked[0]

            if valid and text.endswith('%') and text[:-1].isdigit() and len(text) == len(groups):
                value = int(text[:-1])
                if 0 <= value <= 100:
                    return value
        return None
