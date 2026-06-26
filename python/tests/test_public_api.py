from __future__ import annotations

import unittest

import rp2350_remote_display as rpd
from rp2350_remote_display.protocol import PROTOCOL_VERSION


class PublicApiTests(unittest.TestCase):
    def test_protocol_version_matches_release_target(self) -> None:
        self.assertEqual(PROTOCOL_VERSION, 16)

    def test_public_symbols_are_available(self) -> None:
        for name in (
            "Canvas",
            "CoordinateSpace",
            "DirtyTilePresenter",
            "Layout",
            "RemoteDisplay",
            "RemoteDisplayAccessError",
            "RemoteDisplayError",
            "Rect",
            "rgb565",
        ):
            self.assertTrue(hasattr(rpd, name), name)


if __name__ == "__main__":
    unittest.main()
