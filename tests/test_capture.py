import unittest
from unittest.mock import Mock, patch
from capture import RegionCapture


class CaptureRecoveryTests(unittest.TestCase):
    def test_transient_surface_error_rebuilds_once(self):
        capture = RegionCapture.__new__(RegionCapture)
        capture.close = Mock()
        expected = object()
        capture._grab = Mock(side_effect=[OSError('display changed'), expected])
        with patch.object(RegionCapture, '__init__', return_value=None) as rebuild:
            self.assertIs(capture.grab((0, 0, 10, 10)), expected)
            rebuild.assert_called_once()
        capture.close.assert_called_once()

    def test_persistent_error_propagates_instead_of_looping(self):
        capture = RegionCapture.__new__(RegionCapture)
        capture.close = Mock()
        capture._grab = Mock(side_effect=OSError('unavailable'))
        with patch.object(RegionCapture, '__init__', return_value=None):
            with self.assertRaises(OSError):
                capture.grab((0, 0, 10, 10))
        self.assertEqual(capture._grab.call_count, 2)
