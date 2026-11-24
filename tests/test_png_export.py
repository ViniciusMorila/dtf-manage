import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem, QGraphicsScene

from dtf_manager.services.export_service import ExportService
from dtf_manager.ui.styles import ROLL_OUTLINE_COLOR
from dtf_manager.ui.widgets.artwork_item import ArtworkItem
from dtf_manager.ui.widgets.roll_view import RollView


class PngExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / "art.png"
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(QColor("#3366ee"))
        image.save(str(self.source))
        self.view = RollView()
        self.view.set_roll_settings(20, 2)
        self.view.add_artwork(str(self.source), 4, 6)
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.view.close)
        self.exporter = ExportService()

    def export(self, name="print", height=None, split=None):
        height = height if height is not None else self.view.sceneRect().height()
        with patch("dtf_manager.services.export_service.DOWNLOADS_PATH", self.folder):
            return self.exporter.export_roll(self.view.scene(), 20, height, 254, split, name)

    def test_visible_guide_excluded_artwork_transparency_dimensions_and_repeat(self):
        guide = self.view._roll_outline
        self.assertTrue(guide.isVisible())
        self.assertEqual(guide.pen().color(), QColor(ROLL_OUTLINE_COLOR))
        for name in ("first", "second"):
            image = QImage(str(self.export(name)[0]))
            self.assertEqual((image.width(), image.height()), (200, 60))
            self.assertEqual(image.dotsPerMeterX(), 10000)
            self.assertEqual(image.dotsPerMeterY(), 10000)
            self.assertEqual(image.pixelColor(10, 10), QColor("#3366ee"))
            self.assertEqual(image.pixelColor(199, 20).alpha(), 0)
            self.assertEqual(image.pixelColor(100, 59).alpha(), 0)
            wine = QColor(ROLL_OUTLINE_COLOR)
            self.assertFalse(any(image.pixelColor(x, y) == wine
                                 for x in range(image.width()) for y in range(image.height())))
            self.assertTrue(guide.isVisible())
            self.assertIs(guide.scene(), self.view.scene())
        # Editor rendering still contains the guide at the empty right edge.
        editor = QImage(200, 60, QImage.Format.Format_ARGB32)
        editor.fill(0)
        painter = QPainter(editor)
        try:
            self.view.scene().render(painter, QRectF(0, 0, 200, 60), QRectF(0, 0, 20, 6),
                                     Qt.AspectRatioMode.IgnoreAspectRatio)
        finally:
            painter.end()
        self.assertGreater(editor.pixelColor(199, 20).alpha(), 0)
        self.assertEqual(editor.pixelColor(199, 20).rgb(), QColor(ROLL_OUTLINE_COLOR).rgb())

    def test_selection_pixmap_overlay_and_scene_background_are_not_printed(self):
        art = self.view._artwork_items[str(self.source)][0]
        art.setSelected(True)
        self.view.scene().setBackgroundBrush(QColor("yellow"))
        self.view.scene().addRect(10, 0, 3, 3, brush=QColor("green"))
        overlay = QGraphicsPixmapItem(QPixmap(str(self.source)))
        overlay.setPos(15, 0)
        self.view.scene().addItem(overlay)
        image = QImage(str(self.export()[0]))
        self.assertEqual(image.pixelColor(1, 1), QColor("#3366ee"))
        self.assertEqual(image.pixelColor(120, 10).alpha(), 0)
        self.assertEqual(image.pixelColor(160, 10).alpha(), 0)
        self.assertTrue(art.isSelected())
        self.assertTrue(overlay.isVisible())
        self.assertTrue(self.view._roll_outline.isVisible())

    def test_wine_pixels_belonging_to_artwork_are_preserved(self):
        art = self.view._artwork_items[str(self.source)][0]
        pixmap = QPixmap(10, 10)
        pixmap.fill(QColor(ROLL_OUTLINE_COLOR))
        art.setPixmap(pixmap)
        image = QImage(str(self.export()[0]))
        self.assertEqual(image.pixelColor(10, 10), QColor(ROLL_OUTLINE_COLOR))
        self.assertEqual(image.pixelColor(199, 20).alpha(), 0)

    def test_increased_quantity_remains_printable_and_geometry_unchanged(self):
        self.view.update_artwork_quantity(str(self.source), 3)
        items = self.view._artwork_items[str(self.source)]
        self.assertTrue(all(isinstance(item, ArtworkItem) for item in items))
        before = [(item.pos(), item.transform(), item.pixmap().cacheKey()) for item in items]
        image = QImage(str(self.export()[0]))
        for item in items:
            center = item.sceneBoundingRect().center()
            self.assertEqual(image.pixelColor(round(center.x() * 10), round(center.y() * 10)),
                             QColor("#3366ee"))
        self.assertEqual(before, [(item.pos(), item.transform(), item.pixmap().cacheKey()) for item in items])

    def test_split_dimensions_and_art_positions_are_preserved(self):
        self.view.update_artwork_quantity(str(self.source), 2)
        first, second = self.view._artwork_items[str(self.source)]
        first.setPos(2, 1)                    # 1 .. 7 mm: crosses the 5 mm cut, so part 1 grows to 7.2 mm
        second.setPos(2, 9)                   # 9 .. 15 mm: starts the second part
        paths = self.export(height=16, split=0.005)
        self.assertEqual(len(paths), 2)
        images = [QImage(str(path)) for path in paths]
        self.assertEqual([(image.width(), image.height()) for image in images],
                         [(200, 72), (200, 62)])
        self.assertEqual(images[0].pixelColor(25, 15), QColor("#3366ee"))
        self.assertEqual(images[0].pixelColor(15, 15).alpha(), 0)
        self.assertEqual(images[0].pixelColor(25, 68), QColor("#3366ee"))     # whole art, not cut at 5 mm
        self.assertEqual(images[1].pixelColor(25, 5), QColor("#3366ee"))      # next part starts at the next art
        self.assertEqual(images[1].pixelColor(25, 58), QColor("#3366ee"))

    def test_rotated_scaled_artwork_opacity_and_position_are_preserved(self):
        art = self.view._artwork_items[str(self.source)][0]
        art.setTransform(QTransform().scale(0.4, 0.6).rotate(90))
        art.setPos(9, 2)
        art.setOpacity(0.5)
        bounds = art.sceneBoundingRect()
        transform = art.sceneTransform()
        image = QImage(str(self.export()[0]))
        center = bounds.center()
        self.assertIn(image.pixelColor(round(center.x() * 10), round(center.y() * 10)).alpha(), (127, 128))
        self.assertEqual(image.pixelColor(100, 10).alpha(), 0)
        self.assertEqual(art.sceneBoundingRect(), bounds)
        self.assertEqual(art.sceneTransform(), transform)

    def test_error_during_render_preserves_editor_state(self):
        item = self.view._artwork_items[str(self.source)][0]
        item.setSelected(True)
        with patch.object(QGraphicsScene, "render", side_effect=RuntimeError("render failure")):
            with self.assertRaises(RuntimeError):
                self.export()
        self.assertTrue(self.view._roll_outline.isVisible())
        self.assertTrue(item.isVisible())
        self.assertTrue(item.isSelected())
        self.assertTrue(self.export("after_error")[0].is_file())

    def test_save_failure_preserves_editor_guide(self):
        with patch.object(QImage, "save", return_value=False):
            with self.assertRaises(OSError):
                self.export()
        self.assertTrue(self.view._roll_outline.isVisible())

    def export_via_main_window(self, split=None):
        # Exercise the production caller without constructing the application,
        # touching stock/database state, or starting authentication.
        from dtf_manager.ui.main_window import MainWindow

        settings = Mock()
        settings.width_input.value.return_value = self.view.sceneRect().width() / 10
        settings.auto_split.isChecked.return_value = split is not None
        settings.length_input.value.return_value = split
        stock = Mock()
        stock.export_roll.side_effect = lambda render, **kwargs: render()
        stock.export_stock_shortages = []
        caller = SimpleNamespace(
            _export_progress=95, _export_stage=1, _export_file_name="current_length",
            settings=settings, roll_view=self.view, export_service=self.exporter,
            art_stock_repository=stock, art_stock_page=Mock(),
        )
        with patch("dtf_manager.services.export_service.DOWNLOADS_PATH", self.folder):
            MainWindow._advance_export(caller)
        self.assertEqual(caller._export_stage, 2)
        return caller._output_paths

    def test_main_window_exports_current_length_after_roll_shrinks_at_300_dpi(self):
        self.view.set_roll_settings(1, 0)
        self.view.update_artwork(str(self.source), 1, 15690)
        self.assertGreaterEqual(self.view.scene().sceneRect().height(), 15690)
        self.view.update_artwork(str(self.source), 1, 6805)
        self.assertEqual(self.view.sceneRect().height(), 6805)
        self.assertGreaterEqual(self.view.scene().sceneRect().height(), 15690)
        item = self.view._artwork_items[str(self.source)][0]
        before = (item.pos(), item.transform(), item.pixmap().cacheKey())

        for _ in range(2):
            image = QImage(str(self.export_via_main_window()[0]))
            self.assertEqual((image.width(), image.height()),
                             (round(300 / 25.4), round(6805 * 300 / 25.4)))
            self.assertNotEqual(image.height(), round(15690 * 300 / 25.4))
            self.assertEqual(image.dotsPerMeterX(), 11811)
            self.assertEqual(image.dotsPerMeterY(), 11811)
            self.assertTrue(image.hasAlphaChannel())
            # Full-width opaque artwork reaches the last row: no historic tail
            # and no cropping of the artwork's current physical bounds.
            for y in (0, image.height() // 2, image.height() - 1):
                self.assertEqual(image.pixelColor(image.width() // 2, y), QColor("#3366ee"))
            self.assertTrue(self.view._roll_outline.isVisible())
            self.assertEqual(before, (item.pos(), item.transform(), item.pixmap().cacheKey()))

    def test_current_length_controls_split_after_shrink(self):
        self.view.set_roll_settings(20, 0)
        self.view.update_artwork(str(self.source), 4, 30)
        self.assertGreaterEqual(self.view.scene().sceneRect().height(), 30)
        self.view.update_artwork(str(self.source), 4, 12)
        self.assertGreaterEqual(self.view.scene().sceneRect().height(), 30)
        images = [QImage(str(path)) for path in self.export_via_main_window(split=0.005)]
        self.assertEqual([image.height() for image in images],
                         [round(12 * 300 / 25.4)])
        for image in images:
            self.assertEqual(image.pixelColor(10, image.height() - 1), QColor("#3366ee"))
            self.assertEqual(image.pixelColor(image.width() - 1, 0).alpha(), 0)

    def test_safe_cut_extends_three_metres_to_art_end_with_clearance(self):
        scene = QGraphicsScene()
        art = ArtworkItem(QPixmap(str(self.source)))
        art.setTransform(QTransform().scale(1, 100))
        art.setPos(0, 2500)
        scene.addItem(art)
        # The art is kept whole in the first part (3.5 m + clearance); the empty film after it is not printed.
        self.assertEqual(self.exporter._split_ranges(scene, 7000, 3000), [(0.0, 3500.2)])

    def test_an_art_in_another_column_goes_whole_to_the_next_part_and_overlays_are_ignored(self):
        scene = QGraphicsScene()
        for x, top, bottom in ((0, 4, 7), (12, 7.1, 9)):
            art = ArtworkItem(QPixmap(str(self.source)))
            art.setTransform(QTransform().scale(0.4, (bottom - top) / 10))
            art.setPos(x, top)
            scene.addItem(art)
        scene.addRect(0, 0, 20, 30)
        parts = self.exporter._split_ranges(scene, 20, 5)
        self.assertEqual(len(parts), 2)
        self.assertAlmostEqual(parts[0][1], 7.2)              # the first art, whole, plus clearance
        self.assertAlmostEqual(parts[1][0], 7.1)              # the second starts exactly where its art starts

    def stagger_two_columns(self, total_mm):
        """Columns with slightly different art heights: their gaps only line up every ~9 m."""
        scene = QGraphicsScene()
        for x, height, pitch in ((0, 300, 305), (300, 290, 295)):
            y = 0.0
            while y + height <= total_mm:
                art = ArtworkItem(QPixmap(str(self.source)))
                art.setTransform(QTransform().scale(28, height / 10))
                art.setPos(x, y)
                scene.addItem(art)
                y += pitch
        return scene

    def test_staggered_columns_still_split_at_the_selected_length(self):
        # Regression: 7 m selected on a 38 m roll used to give parts of 18 m (the cut chased the gaps).
        scene = self.stagger_two_columns(38000)
        parts = self.exporter._split_ranges(scene, 38000, 7000)
        self.assertEqual(len(parts), 6)
        for start, length in parts[:-1]:
            self.assertGreaterEqual(length, 7000)
            self.assertLess(length, 7000 + 300 + 1)           # target + at most the art that crosses it
        self.assertLess(parts[-1][1], 7000 + 301)

    def test_no_art_is_cut_and_every_art_is_printed_exactly_once(self):
        scene = self.stagger_two_columns(20000)
        arts = [item for item in scene.items() if isinstance(item, ArtworkItem)]
        plan = self.exporter._plan_parts(scene, 20000, 7000)
        taken = [item for _, _, items in plan for item in items]
        self.assertEqual(len(taken), len(arts))
        self.assertEqual({id(item) for item in taken}, {id(item) for item in arts})
        for start, length, items in plan:
            for item in items:
                bounds = item.mapRectToScene(QRectF(item.offset(), item.pixmap().deviceIndependentSize()))
                self.assertGreaterEqual(bounds.top(), start - 1e-6)
                self.assertLessEqual(bounds.bottom(), start + length + 1e-6)

    def test_an_art_starting_at_the_cut_line_belongs_to_the_next_part(self):
        scene = QGraphicsScene()
        art = ArtworkItem(QPixmap(str(self.source)))
        art.setTransform(QTransform().scale(0.4, 0.2))
        art.setPos(0, 5)
        scene.addItem(art)
        # Empty film before the first art is skipped; the art starts exactly at the cut and is whole.
        self.assertEqual(self.exporter._split_ranges(scene, 15, 5), [(5, 5)])

    def test_manual_position_length_is_used_for_export(self):
        self.view.set_roll_settings(20, 0)
        item = self.view._artwork_items[str(self.source)][0]
        item.setPos(0, 30)
        self.view._finalize_manual_positions()
        self.view.scene().sceneRect()  # Establish the larger historical extent.
        item.setPos(0, 2)
        self.view._finalize_manual_positions()
        current_height = item.sceneBoundingRect().bottom()
        self.assertAlmostEqual(current_height, 8.3)
        self.assertEqual(self.view.sceneRect().height(), current_height)
        self.assertGreaterEqual(self.view.scene().sceneRect().height(), 36)
        image = QImage(str(self.export_via_main_window()[0]))
        self.assertEqual(image.height(), round(current_height * 300 / 25.4))
        self.assertEqual(image.pixelColor(10, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(10, round(7.5 * 300 / 25.4)), QColor("#3366ee"))
