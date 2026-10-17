"""Recognize a tightly selected Collect word without reading item names."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def signature(mask):
    ys,xs = np.nonzero(mask)
    if len(xs)<15:
        return None
    crop = mask[ys.min():ys.max()+1,xs.min():xs.max()+1]
    if crop.shape[0]<6 or not 2.2 < crop.shape[1]/crop.shape[0] < 5.5:
        return None
    return np.asarray(Image.fromarray(crop.astype('uint8')*255).resize((96,28),Image.Resampling.BILINEAR))>110


class CollectReader:
    def __init__(self):
        templates=[]
        for font in ('arialbd.ttf','arial.ttf','segoeuib.ttf','segoeui.ttf','verdanab.ttf','tahomabd.ttf'):
            path=Path('C:/Windows/Fonts')/font
            if not path.exists():
                continue
            for size in (14,20,28):
                im=Image.new('L',(180,70))
                ImageDraw.Draw(im).text((3,3),'Collect',font=ImageFont.truetype(str(path),size),fill=255)
                value=signature(np.asarray(im)>130)
                if value is not None:
                    templates.append(value)
        self.templates=np.stack(templates)

    def read(self,image):
        a=np.asarray(image.convert('RGB')).astype(np.int16)
        white=(a.min(axis=2)>175)&(np.ptp(a,axis=2)<65)
        value=signature(white)
        if value is None:
            return False
        errors=np.logical_xor(self.templates,value).mean(axis=(1,2))
        return bool(errors.min()<.19)
