"""Windows UI acceptance with a fake Defender backend; never changes security."""
import argparse
import json
import os
from pathlib import Path
import time
import tkinter as tk
from unittest.mock import patch

from benchmark_ui import BenchmarkWindow, DefenderAdapter


class FakeDefender:
    enabled = True
    requests = 0
    def status(self):
        return {'available': True, 'RealTimeProtectionEnabled': self.enabled, 'IsTamperProtected': False}
    def request_disable(self):
        self.requests += 1
        self.enabled = False
        return {'available': True, 'RealTimeProtectionEnabled': False, 'requestExitCode': 0}


def pump(root, duration=.25):
    until = time.monotonic() + duration
    while time.monotonic() < until:
        root.update()
        time.sleep(.02)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default='benchmark-ui-evidence')
    args = parser.parse_args()
    output = Path(args.directory)
    output.mkdir(parents=True, exist_ok=True)
    result = {'passed': False, 'defender_backend': 'fake; no real setting changed'}
    root = tk.Tk()
    backend = FakeDefender()
    options = argparse.Namespace(mode='quick', repeats=None, focus='all', directory=str(output / 'results'),
                                 baseline_source=None, final_source=None)
    try:
        window = BenchmarkWindow(root, options, DefenderAdapter(backend))
        pump(root)
        assert window.repeats.get() == 1 and str(window.repeat_input['state']) == 'disabled'
        assert backend.requests == 0
        window.mode.set('thorough')
        window.change_mode()
        assert window.repeats.get() == 3 and str(window.repeat_input['state']) == 'normal'
        with patch('benchmark_ui.messagebox.askyesno', return_value=False):
            window.disable_defender()
        assert backend.requests == 0
        with patch('benchmark_ui.messagebox.askyesno', return_value=True):
            window.disable_defender()
        pump(root)
        assert backend.requests == 1 and backend.enabled is False
        assert 'désactivée' in window.defender_status.get()
        root.update_idletasks()
        placement = window.window_placement
        work = placement['workArea']
        if os.name == 'nt':
            assert placement['nativeWorkArea'], 'Windows work area was not available'
        client = (root.winfo_rootx(), root.winfo_rooty(),
                  root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())
        def inside(box, area):
            return (box[0] >= area[0] and box[1] >= area[1]
                    and box[2] <= area[2] and box[3] <= area[3])
        assert inside(client, work), (client, work)
        if placement['outerBounds'] is not None:
            assert inside(placement['outerBounds'], work), (placement['outerBounds'], work)
        widget_bounds = {}
        for name in ('start_button', 'stop_button', 'cancel_button', 'open_button',
                     'progress', 'reminder_label'):
            widget = getattr(window, name)
            box = (widget.winfo_rootx(), widget.winfo_rooty(),
                   widget.winfo_rootx() + widget.winfo_width(), widget.winfo_rooty() + widget.winfo_height())
            assert widget.winfo_ismapped() and inside(box, client) and inside(box, work), (name, box, client, work)
            widget_bounds[name] = box
        from PIL import ImageGrab
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(output / 'benchmark-window-synthetic.png')
        result.update(passed=True, quickAndThorough=True, boundedRepetitions=True,
                      explicitDefenderOnly=True, actualStateDisplayed=True, manualReminder=True,
                      buttonsInsideWindow=True, buttonsInsideWorkArea=True,
                      initialPlacement=placement, clientBounds=client, visibleWidgetBounds=widget_bounds)
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        root.destroy()
        (output / 'benchmark-ui-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
