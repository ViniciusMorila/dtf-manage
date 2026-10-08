from pathlib import Path
import math
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
        part_count = max(1, math.ceil(height_mm / split_height_mm))
        safe_output_name = self._safe_file_name(output_name)
        DOWNLOADS_PATH.mkdir(parents=True, exist_ok=True)
        print_scene = self._artwork_scene(scene)
        output_paths = []
        for part_index in range(part_count):
            source_y = part_index * split_height_mm
            part_height_mm = min(split_height_mm, height_mm - source_y)
            output_paths.append(
                self._export_part(
                    print_scene,
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
    def _artwork_scene(scene):
        """Copy printable pixels/geometry, never editor guides or selection state."""
        result = QGraphicsScene()
        result.setSceneRect(scene.sceneRect())
        for item in scene.items(Qt.SortOrder.AscendingOrder):
            if not isinstance(item, ArtworkItem) or not item.isVisible():
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
