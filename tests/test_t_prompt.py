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

    def test_offset_circle_inside_padded_selection(self):
        image=Image.new('RGB',(140,100),'#57423c')
        draw=ImageDraw.Draw(image)
        draw.ellipse((70,25,115,70),fill='white')
        draw.text((93,48),'T',anchor='mm',fill='#555555',font=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',22))
        self.assertTrue(TPromptReader().read(image))

    def test_other_key_is_rejected(self):
        image=Image.new('RGB',(100,100),'#57423c')
        draw=ImageDraw.Draw(image)
        draw.ellipse((25,25,70,70),fill='white')
        draw.text((48,48),'E',anchor='mm',fill='#555555',font=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',22))
        self.assertFalse(TPromptReader().read(image))
