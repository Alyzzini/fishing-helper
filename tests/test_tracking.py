import unittest
from PIL import Image, ImageDraw
from app import detect
from control import Tracker


class DetectionTests(unittest.TestCase):
    def make_bar(self, color, dot_y):
        image = Image.new('RGB', (80, 500), '#244763')
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 210, 74, 255), radius=6, outline=color, width=3)
        draw.rounded_rectangle((25, dot_y-12, 54, dot_y+12), radius=4, fill='white')
        return image

    def test_green_and_yellow_targets(self):
        for color in ('#80ff00', '#ffff40'):
            with self.subTest(color=color):
                target, dot = detect(self.make_bar(color, 310))
                self.assertAlmostEqual(target, 232.5, delta=3)
                self.assertAlmostEqual(dot, 310, delta=3)

    def test_dot_near_bottom_is_not_rejected(self):
        result = detect(self.make_bar('#ffff40', 480))
        self.assertIsNotNone(result)
        self.assertGreater(result[1], 470)

    def test_empty_water_has_no_detection(self):
        for color in ('#00e0ff', '#1275cc'):
            self.assertIsNone(detect(Image.new('RGB', (80, 500), color)))


class ControllerTests(unittest.TestCase):
    def test_direction_and_reverse_setting(self):
        for up in (True, False):
            tracker = Tracker()
            self.assertEqual(tracker.decide(200, 260, 1, 5, up, False, 800), up)
            tracker.reset()
            self.assertEqual(tracker.decide(200, 140, 1, 5, up, True, 800), not up)

    def test_brakes_when_approaching_target_quickly(self):
        tracker = Tracker()
        tracker.decide(200, 250, 1, 5, True, True, 800)
        self.assertFalse(tracker.decide(200, 208, 1.02, 5, True, True, 800))

    def test_dead_zone_preserves_current_input(self):
        for held in (True, False):
            self.assertEqual(Tracker().decide(200, 202, 1, 5, True, held, 800), held)

    def test_stale_motion_does_not_affect_new_reading(self):
        tracker = Tracker()
        tracker.decide(200, 250, 1, 5, True, True, 800)
        self.assertTrue(tracker.decide(200, 208, 2, 5, True, True, 800))


if __name__ == '__main__':
    unittest.main()
