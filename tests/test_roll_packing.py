import unittest

from dtf_manager.ui.widgets.roll_view import RollView


class RollPackingTests(unittest.TestCase):
    def test_odd_large_copy_rotates_into_shorter_final_row(self):
        layout = RollView._best_fit_oriented_positions(
            [(200.0, 300.0)] * 3, usable_width=570.0, gap=10.0
        )
        self.assertEqual(
            [(0.0, 0.0, False), (210.0, 0.0, True), (0.0, 310.0, True)],
            layout,
        )
        used_height = max(
            y + (width if rotated else height)
            for (width, height), (x, y, rotated) in zip([(200.0, 300.0)] * 3, layout)
        )
        self.assertEqual(510.0, used_height)

    def test_small_rectangles_are_packed_together_without_overflow(self):
        sizes = [(80.0, 40.0)] * 8
        layout = RollView._best_fit_oriented_positions(sizes, usable_width=570.0, gap=5.0)
        self.assertEqual(len(sizes), len(layout))
        for (width, height), (x, y, rotated) in zip(sizes, layout):
            final_width = height if rotated else width
            self.assertLessEqual(x + final_width, 570.0)

    def test_two_dimensional_grouping_uses_holes_and_keeps_equal_copies_together(self):
        groups = [[(200.0, 300.0)] * 4, [(90.0, 60.0)] * 4]
        layout = RollView._maxrects_grouped_positions(groups, usable_width=570.0, gap=10.0)
        sizes = [size for group in groups for size in group]
        placed = []
        for (width, height), (x, y, rotated) in zip(sizes, layout):
            final_width, final_height = ((height, width) if rotated else (width, height))
            self.assertLessEqual(x + final_width, 570.0)
            for old_x, old_y, old_width, old_height in placed:
                separated = (
                    x >= old_x + old_width + 10.0 - 1e-6
                    or old_x >= x + final_width + 10.0 - 1e-6
                    or y >= old_y + old_height + 10.0 - 1e-6
                    or old_y >= y + final_height + 10.0 - 1e-6
                )
                self.assertTrue(separated)
            placed.append((x, y, final_width, final_height))
        # Copies from each group are emitted consecutively, so equal arts stay clustered.
        self.assertEqual(8, len(layout))

    def test_regroup_variants_produce_safe_alternative_arrangements(self):
        groups = [[(180.0, 260.0)] * 3, [(120.0, 70.0)] * 4, [(45.0, 30.0)] * 5]
        layouts = [
            RollView._maxrects_grouped_positions(groups, 570.0, 5.0, variant)
            for variant in range(8)
        ]
        self.assertGreater(len({tuple(layout) for layout in layouts}), 2)
        sizes = [size for group in groups for size in group]
        for layout in layouts:
            placed = []
            for (width, height), (x, y, rotated) in zip(sizes, layout):
                final_width, final_height = ((height, width) if rotated else (width, height))
                self.assertGreaterEqual(x, -1e-6)
                self.assertLessEqual(x + final_width, 570.0 + 1e-6)
                for old_x, old_y, old_width, old_height in placed:
                    self.assertTrue(
                        x >= old_x + old_width + 5.0 - 1e-6
                        or old_x >= x + final_width + 5.0 - 1e-6
                        or y >= old_y + old_height + 5.0 - 1e-6
                        or old_y >= y + final_height + 5.0 - 1e-6
                    )
                placed.append((x, y, final_width, final_height))


if __name__ == "__main__":
    unittest.main()
