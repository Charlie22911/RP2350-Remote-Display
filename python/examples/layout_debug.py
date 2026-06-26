"""Show coordinate grids, text boxes, widget bounds, and medium tile boundaries."""

from rp2350_remote_display import CoordinateSpace, DebugOverlay, Layout, Rect, RemoteDisplay, rgb565

BLACK = rgb565(5, 7, 13)
PANEL = rgb565(20, 29, 48)
BORDER = rgb565(65, 89, 128)
WHITE = rgb565(243, 247, 255)
CYAN = rgb565(84, 217, 255)
GREEN = rgb565(84, 216, 156)
ORANGE = rgb565(255, 170, 76)

with RemoteDisplay.open(timeout_ms=2000) as display:
    with display.frame(timeout_ms=5000):
        display.clear(BLACK)
        layout = Layout(
            display,
            space=CoordinateSpace.design(1000, 1000),
            debug=DebugOverlay(enabled=True, minor_grid=25, major_grid=100, show_bounds=True, show_tile_profile="medium"),
        )
        layout.begin_debug_overlay()
        header = layout.region("header", layout.rect(40, 40, 920, 130))
        left, right = layout.rect(40, 210, 920, 540).split_columns(2, gap=32)
        layout.fill(header, PANEL)
        layout.stroke(header, BORDER, 2)
        layout.text_box(header.inset(24), "Layout and coordinate diagnostics", WHITE, font_size=18, align="center", valign="middle", label="title")
        layout.fill(left, PANEL)
        layout.stroke(left, BORDER, 2)
        layout.line_chart(left.inset(22), [12, 26, 19, 40, 33, 58, 51, 71], line_color=CYAN, grid_color=BORDER, background=PANEL, label="line chart")
        layout.fill(right, PANEL)
        layout.stroke(right, BORDER, 2)
        chart, controls = right.inset(22).split_rows(2, gap=18)
        layout.bar_chart(chart, [20, 43, 31, 58, 74, 45], bar_color=GREEN, grid_color=BORDER, background=PANEL, label="bar chart")
        layout.button(controls, "Apply", background=ORANGE, border=WHITE, text_color=BLACK, label="apply")
        layout.end_debug_overlay()

print("Layout diagnostic frame presented.")
