from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import sys
from io import StringIO
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "examples" / "plasma_interactive.py"
SPEC = importlib.util.spec_from_file_location("rpd_plasma_interactive", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
plasma = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plasma
SPEC.loader.exec_module(plasma)


class PlasmaInteractiveTests(unittest.TestCase):
    def test_help_lists_every_live_control(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            plasma.show_help()
        controls = output.getvalue()
        for token in ("[1]", "[2]", "[3]", "[4]", "[d]", "[h]", "[?]", "[q]"):
            self.assertIn(token, controls)

    def test_wrapped_plasma_fields_use_whole_cycle_counts(self) -> None:
        for cycle_count in (
            plasma.X_CYCLES,
            plasma.Y_CYCLES,
            plasma.DIAGONAL_X_CYCLES,
            plasma.DIAGONAL_Y_CYCLES,
        ):
            self.assertEqual(cycle_count, int(cycle_count))

    def test_colour_lut_is_dark_muted_and_smooth(self) -> None:
        lut = plasma.PlasmaRenderer._make_color_lut()
        self.assertEqual(len(lut), 256 * 3)
        red, green, blue = lut[:256], lut[256:512], lut[512:]
        self.assertLessEqual(max(red[0], green[0], blue[0]), 16)
        self.assertGreater(max(red), 150)
        for channel in (red, green, blue):
            self.assertLessEqual(
                max(abs(channel[index + 1] - channel[index]) for index in range(255)),
                3,
            )

    def test_renderer_outputs_rgb_at_full_and_half_resolution(self) -> None:
        full = plasma.PlasmaRenderer(plasma.WIDTH, plasma.HEIGHT).render(7)
        half = plasma.PlasmaRenderer(plasma.HALF_WIDTH, plasma.HALF_HEIGHT).render(7)
        self.assertEqual((full.mode, full.size), ("RGB", (plasma.WIDTH, plasma.HEIGHT)))
        self.assertEqual((half.mode, half.size), ("RGB", (plasma.HALF_WIDTH, plasma.HALF_HEIGHT)))


if __name__ == "__main__":
    unittest.main()
