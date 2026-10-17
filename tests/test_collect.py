import unittest
from PIL import Image, ImageDraw, ImageFont
from collect_prompt import CollectReader


class CollectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader=CollectReader()

    def word(self,text):
        image=Image.new('RGB',(160,42),'#443d34')
        ImageDraw.Draw(image).text((5,3),text,fill='white',font=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',20))
        return image

    def test_collect_is_recognized(self):
        self.assertTrue(self.reader.read(self.word('Collect')))

    def test_other_words_and_blank_are_rejected(self):
        for word in ('Cancel','Drop','Exit','Craft',''):
            with self.subTest(word=word):
                self.assertFalse(self.reader.read(self.word(word)))
