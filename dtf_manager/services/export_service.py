from pathlib import Path
import re

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene

from dtf_manager.core.constants import DOWNLOADS_PATH
from dtf_manager.ui.widgets.artwork_item import ArtworkItem


class ExportService:
    """Renders the current transparent roll and saves it as a PNG."""

    def export_roll(
        self,
        scene,
        width_mm: float,
        height_mm: float,
        dpi: int,
        max_length_m: float | None = None,
        output_name: str = "DTF_Manager_export",
    ) -> list[Path]:
        if width_mm <= 0 or height_mm <= 0 or dpi <= 0:
            raise ValueError("As dimensoes do rolo e o DPI precisam ser maiores que zero.")

        split_height_mm = (
            max_length_m * 1000.0
            if max_length_m is not None and max_length_m > 0
            else height_mm
        )
        parts = self._plan_parts(scene, height_mm, split_height_mm)
        part_count = len(parts)
        safe_output_name = self._safe_file_name(output_name)
        DOWNLOADS_PATH.mkdir(parents=True, exist_ok=True)
        output_paths = []
        for part_index, (source_y, part_height_mm, part_items) in enumerate(parts):
            output_paths.append(
                self._export_part(
                    self._artwork_scene(scene, part_items),
                    width_mm,
                    part_height_mm,
                    source_y,
                    dpi,
                    part_index + 1,
                    part_count,
                    safe_output_name,
                )
            )
        return output_paths

    @staticmethod
    def _printable_items(scene):
        return [item for item in scene.items()
                if isinstance(item, ArtworkItem) and item.isVisible()]

    @staticmethod
    def _item_span(item):
        bounds = item.mapRectToScene(QRectF(item.offset(), item.pixmap().deviceIndependentSize()))
        return bounds.top(), bounds.bottom()

    @classmethod
    def _plan_parts(cls, scene, height_mm, target_mm):
        """Parts of about `target_mm`, without ever cutting an artwork.

        Every artwork belongs to the part where it STARTS and is printed whole there. When one
        crosses the nominal cut it only makes that part a little longer (7 m becomes 7.3 m); the
        next part starts at the first artwork that was not taken. Nothing chains from column to
        column, so a part never grows beyond the target plus the tallest artwork.
        Returns [(source_y_mm, part_height_mm, [ArtworkItem, ...])].
        """
        remaining = sorted(((*cls._item_span(item), item) for item in cls._printable_items(scene)),
                           key=lambda entry: (entry[0], entry[1]))
        if not remaining:
            return [(0.0, height_mm, [])]
        parts = []
        start = 0.0                                   # the first part keeps the top of the roll
        while remaining:
            end = start + target_mm
            taken = [entry for entry in remaining if entry[0] < end]
            if not taken:                             # empty film before the next artwork
                start = remaining[0][0]
                continue
            remaining = [entry for entry in remaining if entry[0] >= end]
            last_bottom = max(bottom for _, bottom, _ in taken)
            end = min(height_mm, max(end, last_bottom + 0.2))   # 0.2 mm of clearance below the art
            parts.append((start, end - start, [item for _, _, item in taken]))
            if remaining:
                start = remaining[0][0]               # no blank film at the top of the next part
        return parts

    @classmethod
    def _split_ranges(cls, scene, height_mm, target_mm):
        return [(start, length) for start, length, _ in cls._plan_parts(scene, height_mm, target_mm)]

    @staticmethod
    def _artwork_scene(scene, only_items=None):
        """Copy printable pixels/geometry, never editor guides or selection state.

        `only_items` limits the copy to the artworks of one part (each one is printed whole)."""
        result = QGraphicsScene()
        result.setSceneRect(scene.sceneRect())
        wanted = None if only_items is None else {id(item) for item in only_items}
        for item in scene.items(Qt.SortOrder.AscendingOrder):
            if not isinstance(item, ArtworkItem) or not item.isVisible():
                continue
            if wanted is not None and id(item) not in wanted:
                continue
            copy = QGraphicsPixmapItem(item.pixmap())
            copy.setOffset(item.offset())
            copy.setTransform(item.sceneTransform())
            copy.setOpacity(item.effectiveOpacity())
            copy.setZValue(item.zValue())
            copy.setTransformationMode(item.transformationMode())
            copy.setShapeMode(item.shapeMode())
            result.addItem(copy)
        return result

    def _export_part(
        self,
        scene,
        width_mm: float,
        height_mm: float,
        source_y_mm: float,
        dpi: int,
        part_number: int,
        part_count: int,
        output_name: str,
    ) -> Path:
        pixels_per_mm = dpi / 25.4
        pixel_width = max(1, round(width_mm * pixels_per_mm))
        pixel_height = max(1, round(height_mm * pixels_per_mm))
        image = QImage(pixel_width, pixel_height, QImage.Format.Format_ARGB32)
        if image.isNull():
            raise OSError(
                "O rolo e grande demais para ser exportado em uma unica imagem a 300 DPI."
            )
        image.fill(0)
        image.setDotsPerMeterX(round(dpi / 0.0254))
        image.setDotsPerMeterY(round(dpi / 0.0254))
        painter = QPainter(image)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.LosslessImageRendering
        )
        source_rect = QRectF(0, source_y_mm, width_mm, height_mm)
        target_rect = QRectF(0, 0, image.width(), image.height())
        try:
            scene.render(painter, target_rect, source_rect, Qt.AspectRatioMode.IgnoreAspectRatio)
        finally:
            painter.end()
        file_name = (
            f"{output_name}.png"
            if part_count == 1
            else f"{output_name}_parte_{part_number:02d}_de_{part_count:02d}.png"
        )
        output_path = DOWNLOADS_PATH / file_name
        if not image.save(str(output_path), "PNG"):
            raise OSError(f"Nao foi possivel salvar o arquivo em {output_path}")
        return output_path

    @staticmethod
    def _safe_file_name(file_name: str) -> str:
        name = file_name.strip()
        if name.lower().endswith(".png"):
            name = name[:-4]
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(". ")
        return name or "DTF_Manager_export"
