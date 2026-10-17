"""Detect the dark T glyph inside a tightly selected white key circle."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def shape(mask):
    ys,xs=np.nonzero(mask)
    if len(xs)<4:
        return None
    cut=mask[ys.min():ys.max()+1,xs.min():xs.max()+1]
    if not .35 < cut.shape[1]/cut.shape[0] < 1.8:
        return None
    return np.asarray(Image.fromarray(cut.astype('uint8')*255).resize((24,32),Image.Resampling.BILINEAR))>110


class TPromptReader:
    def __init__(self):
        templates=[]
        for name in ('arialbd.ttf','arial.ttf','segoeuib.ttf','tahomabd.ttf'):
            for size in (14,20,28):
                image=Image.new('L',(60,60))
                ImageDraw.Draw(image).text((4,4),'T',font=ImageFont.truetype('C:/Windows/Fonts/'+name,size),fill=255)
                templates.append(shape(np.asarray(image)>120))
        self.templates=np.stack(templates)

    def _read_circle(self,image):
        a=np.asarray(image.convert('RGB')).astype(np.int16)
        h,w=a.shape[:2]
        if min(h,w)<12 or not .65<w/h<1.5:
            return False
        white=(a.min(2)>190)&(np.ptp(a,axis=2)<50)
        if white.mean()<.35:
            return False
        # The selected circle's central area excludes its rim and surroundings.
        center=a[int(h*.22):int(h*.80),int(w*.24):int(w*.77)]
        glyph=shape(center.max(2)<160)
        if glyph is None:
            return False
        return bool(np.logical_xor(self.templates,glyph).mean(axis=(1,2)).min()<.20)

    def read(self, image):
        if self._read_circle(image):
            return True
        # Locate white connected components so padding and small rod movements
        # do not change the central glyph crop. Bound work for large selections.
        image = image.convert('RGB').copy()
        image.thumbnail((320, 320))
        a = np.asarray(image).astype(np.int16)
        mask = (a.min(2) > 190) & (np.ptp(a, axis=2) < 50)
        h, w = mask.shape
        for y, x in zip(*np.nonzero(mask)):
            if not mask[y, x]:
                continue
            stack = [(int(y), int(x))]
            mask[y, x] = False
            left = right = int(x)
            top = bottom = int(y)
            count = 0
            while stack:
                cy, cx = stack.pop()
                count += 1
                left, right = min(left,cx), max(right,cx)
                top, bottom = min(top,cy), max(bottom,cy)
                for ny,nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny,nx]:
                        mask[ny,nx] = False
                        stack.append((ny,nx))
            cw, ch = right-left+1, bottom-top+1
            if min(cw,ch) >= 12 and .75 < cw/ch < 1.3 and .4 < count/(cw*ch) < .9:
                if self._read_circle(image.crop((left,top,right+1,bottom+1))):
                    return True
        return False
