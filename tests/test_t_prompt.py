import unittest
from PIL import Image,ImageDraw,ImageFont
from pickup_prompt import TPromptReader


class TPromptTests(unittest.TestCase):
    def test_white_circle_with_t(self):
        image=Image.new('RGB',(48,48),'#57423c')
        draw=ImageDraw.Draw(image)
        draw.ellipse((1,1,46,46),fill='white')
        draw.text((24,24),'T',anchor='mm',fill='#555555',font=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',22))
        self.assertTrue(TPromptReader().read(image))

    def test_blank_circle_and_water_are_not_t(self):
        reader=TPromptReader()
        for color in ('white','#1295ff','#443322'):
            self.assertFalse(reader.read(Image.new('RGB',(48,48),color)))
