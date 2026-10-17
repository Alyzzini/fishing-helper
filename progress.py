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
        r,g,b = a[:,:,0],a[:,:,1],a[:,:,2]
        colored = ((r > 130) & (r > g*1.15) & (r > b*1.05)) | ((g > 130) & (g > r*1.15) & (g > b*1.05))
        colored |= (r > 150) & (g > 150) & (b < np.minimum(r,g)*.8)
        # Prefer colored percentage text; white is a fallback for alternate UI themes.
        masks = [colored, (a.min(axis=2) > 210) & (np.ptp(a,axis=2) < 35)]
        for mask in masks:
            cols = np.flatnonzero(mask.sum(axis=0) > 0)
            groups = np.split(cols, np.flatnonzero(np.diff(cols) > 1)+1)
            if not 2 <= len(groups) <= 4 or any(len(v) == 0 for v in groups):
                continue
            text = ''
            for group in groups:
                cut = mask[:,group[0]:group[-1]+1]
                ys,xs = np.nonzero(cut)
                if len(ys) < 5 or ys.max()-ys.min() < 6:
                    break
                ratio = (xs.max()-xs.min()+1)/(ys.max()-ys.min()+1)
                norm = normalize(cut)
                comparisons = np.logical_xor(norm,self.template_masks).mean(axis=(1,2))
                comparisons += np.minimum(.3,np.abs(ratio-self.template_ratios)*.16)
                best = comparisons.reshape(-1,11).min(axis=0)
                scores = dict(zip('0123456789%',best))
                ranked = sorted(scores, key=scores.get)
                if scores[ranked[0]] > .23 or scores[ranked[1]]-scores[ranked[0]] < .012:
                    break
                text += ranked[0]
            if text.endswith('%') and text[:-1].isdigit() and len(text) == len(groups):
                value = int(text[:-1])
                if 0 <= value <= 100:
                    return value
        return None
