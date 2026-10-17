import unittest
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from progress import PercentageReader


class PercentageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = PercentageReader()

    def test_completion_boundary_and_other_values(self):
        for font in ('arialbd.ttf', 'segoeuib.ttf', 'verdanab.ttf'):
            for value in (0, 17, 66, 97, 98, 99, 100):
                with self.subTest(font=font, value=value):
                    image = Image.new('RGB', (160, 60), '#354355')
                    ImageDraw.Draw(image).text((5, 2), f'{value}%', fill='#ff3344',
                        font=ImageFont.truetype(str(Path('C:/Windows/Fonts')/font), 29))
                    self.assertEqual(self.reader.read(image), value)

    def test_blank_is_unreadable(self):
        self.assertIsNone(self.reader.read(Image.new('RGB', (100, 40), '#354355')))


if __name__ == '__main__':
    unittest.main()
