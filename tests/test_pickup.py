import ctypes
import unittest
from unittest.mock import Mock, patch
import numpy as np
from app import App
from keyboard_input import Input, t_event


class PickupTests(unittest.TestCase):
    def setUp(self):
        self.helper = App.__new__(App)
        h = self.helper
        h.state = 'tracking'
        h.progress_due = 0
        h.progress_region = (0, 0, 100, 40)
        h.region = (0, 0, 80, 500)
        h.progress_armed = True
        h.finish_reads = 0
        h.detail_due = 0
        h.frames = 0
        h.fps_started = 10
        h.seen = 0
        h.held = False
        h.test_hold = False
        h.tracker = Mock()
        h.reader = Mock()
        h.capture = Mock()
        h.percent_capture = Mock()
        h.percent_capture.grab.return_value = np.zeros((40, 100, 3), dtype=np.uint8)
        for name in ('detail', 'performance', 'progress_text'):
            setattr(h, name, Mock())
        for name in ('mouse', 'key_t', 'label', 'tracking_lines'):
            setattr(h, name, Mock())
        h.game_focused = Mock(return_value=True)
        h.finish_settings = {key: Mock(get=Mock(return_value=value)) for key, value in {
            'finish_percent': 98, 'wait_seconds': 1.5,
            'hold_seconds': 3.5, 'click_seconds': .1,
        }.items()}
        self.clock = 10.0
        self.time_patch = patch('app.time.monotonic', side_effect=lambda: self.clock)
        self.detect_patch = patch('app.detect', return_value=None)
        self.key_patch = patch('app.user32.GetAsyncKeyState', return_value=0x8000)
        for p in (self.time_patch, self.detect_patch, self.key_patch):
            p.start()
            self.addCleanup(p.stop)

    def step(self, when, percentage):
        self.clock = when
        self.helper.reader.read.return_value = percentage
        self.helper.step()

    def test_lost_tracking_and_low_progress_never_trigger_t(self):
        for i in range(20):
            self.step(10+i*.2, 17)
        self.helper.key_t.assert_not_called()

    def test_unreadable_resets_completion_confirmation(self):
        self.step(10, 98)
        self.step(10.2, None)
        self.step(10.4, 98)
        self.assertNotEqual(self.helper.state, 'finish_wait')
        self.helper.key_t.assert_not_called()

    def test_exact_pickup_sequence_and_single_click(self):
        h = self.helper
        self.step(10, 98)
        self.step(10.2, 99)
        self.assertEqual(h.state, 'finish_wait')
        h.key_t.assert_not_called()
        self.step(11.69, None)
        h.key_t.assert_not_called()
        self.step(11.7, None)
        h.key_t.assert_called_once_with(True)
        self.step(15.19, None)
        h.key_t.assert_called_once_with(True)
        self.step(15.2, None)
        self.assertEqual(h.key_t.call_args.args, (False,))
        self.assertEqual(h.mouse.call_args.args, (True,))
        self.step(15.31, None)
        self.assertEqual(h.mouse.call_args.args, (False,))
        self.assertEqual(sum(c.args == (True,) for c in h.mouse.call_args_list), 1)

    def test_settings_are_snapshotted_for_active_pickup(self):
        h = self.helper
        h.finish_settings['finish_percent'].get.return_value = 99
        h.finish_settings['wait_seconds'].get.return_value = 2.2
        h.finish_settings['hold_seconds'].get.return_value = 4.6
        h.finish_settings['click_seconds'].get.return_value = .25
        self.step(10, 98)
        self.assertEqual(h.finish_reads, 0)
        self.step(10.2, 99)
        self.step(10.4, 99)
        self.assertAlmostEqual(h.deadline, 12.6)
        h.finish_settings['hold_seconds'].get.return_value = 1
        self.step(12.61, None)
        self.assertAlmostEqual(h.deadline, 17.21)
        self.step(17.22, None)
        self.assertAlmostEqual(h.deadline, 17.47)

    def test_scan_code_layout(self):
        self.assertEqual(ctypes.sizeof(Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        self.assertEqual(t_event(True).data.ki.wScan, 0x14)
        self.assertEqual(t_event(True).data.ki.dwFlags, 8)
        self.assertEqual(t_event(False).data.ki.dwFlags, 10)

    def test_unconfirmed_key_never_counts_as_hold_or_clicks(self):
        h = self.helper
        h.state = 'finish_pending'
        h.pickup_hold_seconds = 3.5
        h.stop = Mock()
        with patch('app.user32.GetAsyncKeyState',return_value=0):
            self.step(10,None)
            self.assertIsNone(h.deadline)
            self.step(10.26,None)
            self.step(10.52,None)
            self.step(10.78,None)
        self.assertEqual(h.key_t.call_count,3)
        h.key_t.assert_called_with(True,force=True)
        h.stop.assert_called_once()
        h.mouse.assert_not_called()

    def test_interrupted_hold_requires_full_duration_after_recovery(self):
        h = self.helper
        h.state = 'finish_pending'
        h.pickup_hold_seconds = 3.5
        h.pickup_click_seconds = .1
        self.step(10,None)
        with patch('app.user32.GetAsyncKeyState',return_value=0):
            self.step(12,None)
        self.assertIsNone(h.deadline)
        h.key_t.assert_called_with(True,force=True)
        self.step(12.1,None)
        self.assertAlmostEqual(h.deadline,15.6)
        self.step(13.5,None)
        h.mouse.assert_not_called()
        self.step(15.61,None)
        h.mouse.assert_called_once_with(True)

    def test_manual_test_does_not_cast(self):
        h = self.helper
        h.state = 'finish_pending'
        h.pickup_hold_seconds = 1
        h.test_hold = True
        h.stop = Mock()
        self.step(10,None)
        self.step(11.01,None)
        h.stop.assert_called_once()
        h.mouse.assert_not_called()
        self.assertEqual(h.key_t.call_args.args,(False,))


if __name__ == '__main__':
    unittest.main()
