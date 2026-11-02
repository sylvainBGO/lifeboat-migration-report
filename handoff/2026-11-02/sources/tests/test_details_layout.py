"""Layout regressions; real Tk checks run when a graphical display is available."""
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch
import tkinter as tk

if os.name != 'nt':
    sys.modules.setdefault('winreg', types.ModuleType('winreg'))
from codex_transfer.gui import TransferApp


class DetailsLayoutTest(unittest.TestCase):
    def test_content_keeps_requested_height_on_small_screen(self):
        canvas = Mock()
        canvas.winfo_width.return_value = 1060
        canvas.winfo_height.return_value = 600
        panel = Mock()
        panel.winfo_reqheight.return_value = 850
        app = types.SimpleNamespace(body_canvas=canvas, main_panel=panel, body_window=1)
        TransferApp._resize_body(app)
        canvas.itemconfigure.assert_called_once_with(1, width=1060, height=850)
        canvas.configure.assert_called_once_with(scrollregion=canvas.bbox.return_value)

    def test_closed_details_does_not_scroll(self):
        app = Mock(details_visible=False)
        TransferApp._reveal_details(app)
        app.body_canvas.yview_moveto.assert_not_called()

    def test_open_details_scrolls_after_layout(self):
        app = Mock(details_visible=True)
        TransferApp._reveal_details(app)
        self.assertEqual(app.mock_calls, [
            unittest.mock.call.update_idletasks(), unittest.mock.call._resize_body(),
            unittest.mock.call.body_canvas.yview_moveto(1.0)])

    def test_real_tk_small_window(self):
        try:
            probe = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        probe.destroy()
        with patch('codex_transfer.gui.windows.launched_from_compressed_folder', return_value=False), patch('codex_transfer.gui.windows.removable_drives', return_value=[]):
            app = TransferApp()
            try:
                app.geometry('1080x720')
                app._show_tab('restore')
                app._append_log('Diagnostic test entry')
                app.update()
                app.details_button.invoke()
                app.update()
                self.assertTrue(app.details_visible)
                self.assertGreater(app.log.winfo_height(), 40)
                self.assertIn('Diagnostic test entry', app.log.get('1.0', 'end'))
                self.assertLess(app.log.winfo_rooty(), app.body_canvas.winfo_rooty()+app.body_canvas.winfo_height())
                self.assertGreaterEqual(app.log.winfo_rooty(), app.body_canvas.winfo_rooty())
                app.details_button.invoke()
                app.update()
                self.assertFalse(app.log_frame.winfo_ismapped())
            finally:
                app.destroy()
