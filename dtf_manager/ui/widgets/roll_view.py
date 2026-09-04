from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QFrame, QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QPushButton

from dtf_manager.ui.styles import ROLL_OUTLINE_COLOR


class RollView(QGraphicsView):
    """Transparent roll canvas whose scene coordinates are millimetres."""

    used_length_changed = Signal(float)
    selected_copy_removed = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.scene().selectionChanged.connect(self._selection_changed)
        self._zoom = 1.0
        self._film_width_mm = 570.0
        self._gap_mm = 10.0
        self._artwork_items: dict[str, list[QGraphicsPixmapItem]] = {}
        self._artwork_sizes: dict[str, tuple[float, float]] = {}
        self._group_repetitions = False
        self._regroup_variant = -1
        self._roll_outline: QGraphicsRectItem | None = None
        self.setObjectName("rollView")
        self.setSceneRect(0, 0, 570, 0)
        self.setBackgroundBrush(Qt.BrushStyle.NoBrush)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self._is_panning = False
        self._pan_start = None
        self._build_action_bar()
        self.hide()

    def _build_action_bar(self) -> None:
        self.action_bar = QFrame(self.viewport())
        self.action_bar.setObjectName("selectedArtworkActions")
        actions = QHBoxLayout(self.action_bar)
        actions.setContentsMargins(4, 4, 4, 4)
        actions.setSpacing(3)
        color_button = self._action_button("◐", "Alternar entre preto e branco")
        rotate_button = self._action_button("↻", "Rotacionar 90 graus")
        delete_button = self._action_button("×", "Excluir esta cópia")
        color_button.clicked.connect(self.toggle_selected_color)
        rotate_button.clicked.connect(self.rotate_selected_artwork)
        delete_button.clicked.connect(self.delete_selected_artwork)
        actions.addWidget(color_button)
        actions.addWidget(rotate_button)
        actions.addWidget(delete_button)
        self.action_bar.adjustSize()
        self.action_bar.hide()

    @staticmethod
    def _action_button(text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("artworkActionButton")
        button.setFixedSize(34, 34)
        button.setToolTip(tooltip)
        return button

    def _draw_roll_outline(self):
        outline = QPen(QColor(ROLL_OUTLINE_COLOR), 2, Qt.PenStyle.SolidLine)
        outline.setCosmetic(True)
        height_mm = max(0.0, self.scene().sceneRect().height())
        item = QGraphicsRectItem(0, 0, self._film_width_mm, height_mm)
        item.setPen(outline)
        item.setBrush(Qt.BrushStyle.NoBrush)
        item.setZValue(-1)
        self.scene().addItem(item)
        self._roll_outline = item

    def set_roll_settings(self, film_width_mm: float, gap_mm: float) -> None:
        self._film_width_mm = max(1.0, film_width_mm)
        self._gap_mm = max(0.0, gap_mm)
        if self._roll_outline is not None:
            self.scene().removeItem(self._roll_outline)
            del self._roll_outline
        self.setSceneRect(0, 0, self._film_width_mm, max(1200.0, self.scene().sceneRect().height()))
        if self._artwork_items:
            self._draw_roll_outline()
        self._repack_artworks()

    def set_zoom(self, zoom: float) -> None:
        zoom = max(0.25, min(4.0, zoom))
        self.resetTransform()
        self.scale(zoom, zoom)
        self._zoom = zoom
        self._position_action_bar()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.15)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.15)

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    def add_artwork(self, file_path: str, width_mm: float, height_mm: float, quantity: int = 1) -> None:
        source_path = file_path.split("|dtf-size=", 1)[0]
        pixmap = QPixmap(source_path)
        if pixmap.isNull():
            return
        color_mode = (
            file_path.rsplit("|dtf-color=", 1)[1]
            if "|dtf-color=" in file_path else "original"
        )
        if color_mode in {"black", "white"}:
            recolored = pixmap.copy()
            painter = QPainter(recolored)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(recolored.rect(), QColor("#000000" if color_mode == "black" else "#ffffff"))
            painter.end()
            pixmap = recolored
        items = self._artwork_items.setdefault(file_path, [])
        for _ in range(max(1, quantity)):
            item = QGraphicsPixmapItem(pixmap)
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            item.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
            item.setTransform(self._physical_transform(pixmap, width_mm, height_mm))
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self.scene().addItem(item)
            items.append(item)
        self._artwork_sizes[file_path] = (width_mm, height_mm)
        self.show()
        self._repack_artworks()

    def update_artwork(self, file_path: str, width_mm: float, height_mm: float) -> None:
        items = self._artwork_items.get(file_path)
        if items is not None:
            self._artwork_sizes[file_path] = (width_mm, height_mm)
            self._repack_artworks()

    def update_artwork_quantity(self, file_path: str, quantity: int) -> None:
        items = self._artwork_items.get(file_path)
        if items is None:
            return
        quantity = max(1, quantity)
        if quantity > len(items):
            pixmap = items[0].pixmap()
            rotation = int(items[0].data(0) or 0)
            for _ in range(quantity - len(items)):
                item = QGraphicsPixmapItem(pixmap)
                item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
                item.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
                item.setData(0, rotation)
                self.scene().addItem(item)
                items.append(item)
        else:
            for item in items[quantity:]:
                self.scene().removeItem(item)
            del items[quantity:]
        self._repack_artworks()

    def remove_artwork(self, file_path: str) -> None:
        items = self._artwork_items.pop(file_path, None)
        if items is not None:
            for item in items:
                self.scene().removeItem(item)
                del item
            self._artwork_sizes.pop(file_path, None)
            self._repack_artworks()

    def clear_artworks(self) -> None:
        self.scene().clearSelection()
        for items in self._artwork_items.values():
            for item in items:
                self.scene().removeItem(item)
        self._artwork_items.clear()
        self._artwork_sizes.clear()
        self._group_repetitions = False
        self._regroup_variant = -1
        self._repack_artworks()

    @property
    def has_artworks(self) -> bool:
        return bool(self._artwork_items)

    def artwork_quantity(self, file_path: str) -> int:
        return len(self._artwork_items.get(file_path, ()))

    def select_artwork(self, file_path: str) -> None:
        self.scene().clearSelection()
        for item in self._artwork_items.get(file_path, []):
            item.setSelected(True)
        self._selection_changed()

    def regroup_artworks(self) -> None:
        self._group_repetitions = True
        self._regroup_variant = (self._regroup_variant + 1) % 8
        self.scene().clearSelection()
        self._repack_artworks()

    def _selection_changed(self) -> None:
        selected_items = [
            item
            for item in self.scene().selectedItems()
            if isinstance(item, QGraphicsPixmapItem)
        ]
        if not selected_items:
            self.action_bar.hide()
            return
        self.action_bar.show()
        self.action_bar.raise_()
        self._position_action_bar()

    def _position_action_bar(self) -> None:
        selected_items = self.scene().selectedItems()
        if not selected_items or not self.action_bar.isVisible():
            return
        scene_rect = selected_items[0].sceneBoundingRect()
        top_left = self.mapFromScene(scene_rect.topLeft())
        top_right = self.mapFromScene(scene_rect.topRight())
        x = round((top_left.x() + top_right.x() - self.action_bar.width()) / 2)
        y = top_left.y() - self.action_bar.height() - 6
        x = max(4, min(x, self.viewport().width() - self.action_bar.width() - 4))
        self.action_bar.move(x, max(4, y))

    def toggle_selected_color(self) -> None:
        selected_items = [
            item
            for item in self.scene().selectedItems()
            if isinstance(item, QGraphicsPixmapItem)
        ]
        recolored_cache = {}
        for item in selected_items:
            target_name = self._opposite_color_name(item.pixmap())
            cache_key = (item.pixmap().cacheKey(), target_name)
            recolored = recolored_cache.get(cache_key)
            if recolored is None:
                target_color = QColor("#ffffff" if target_name == "branco" else "#000000")
                recolored = item.pixmap().copy()
                painter = QPainter(recolored)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(recolored.rect(), target_color)
                painter.end()
                recolored_cache[cache_key] = recolored
            item.setPixmap(recolored)
        self._selection_changed()

    def rotate_selected_artwork(self) -> None:
        rotated_cache = {}
        for item in self.scene().selectedItems():
            if not isinstance(item, QGraphicsPixmapItem):
                continue
            cache_key = item.pixmap().cacheKey()
            rotated = rotated_cache.get(cache_key)
            if rotated is None:
                rotated = item.pixmap().transformed(
                    QTransform().rotate(90),
                    Qt.TransformationMode.SmoothTransformation,
                )
                rotated_cache[cache_key] = rotated
            item.setPixmap(rotated)
            item.setData(0, (int(item.data(0) or 0) + 1) % 4)
        self._repack_artworks()
        self._selection_changed()

    def delete_selected_artwork(self) -> None:
        selected_items = [
            item for item in self.scene().selectedItems()
            if isinstance(item, QGraphicsPixmapItem)
        ]
        selected_set = set(selected_items)
        changed_quantities = {}
        for file_path, items in list(self._artwork_items.items()):
            remaining_items = [item for item in items if item not in selected_set]
            if len(remaining_items) == len(items):
                continue
            for item in items:
                if item in selected_set:
                    self.scene().removeItem(item)
            self._artwork_items[file_path] = remaining_items
            quantity = len(remaining_items)
            if quantity == 0:
                self._artwork_items.pop(file_path)
                self._artwork_sizes.pop(file_path, None)
            changed_quantities[file_path] = quantity
        for file_path, quantity in changed_quantities.items():
            self.selected_copy_removed.emit(file_path, quantity)
        self._repack_artworks()

    @staticmethod
    def _opposite_color_name(pixmap: QPixmap) -> str:
        sample = pixmap.toImage().scaled(
            32,
            32,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        luminance_total = 0.0
        visible_pixels = 0
        for y in range(sample.height()):
            for x in range(sample.width()):
                color = sample.pixelColor(x, y)
                if color.alpha() < 32:
                    continue
                luminance_total += (
                    color.red() * 0.2126
                    + color.green() * 0.7152
                    + color.blue() * 0.0722
                )
                visible_pixels += 1
        average_luminance = luminance_total / visible_pixels if visible_pixels else 255.0
        return "preto" if average_luminance >= 128 else "branco"

    def _repack_artworks(self) -> None:
        if not self._artwork_items:
            self.setSceneRect(0, 0, self._film_width_mm, 0)
            self.hide()
            if self._roll_outline is not None:
                self.scene().removeItem(self._roll_outline)
                self._roll_outline = None
            self.used_length_changed.emit(0.0)
            return
        rectangles = []
        grouped_rectangles = []
        # The configured gap separates artworks; it is not an extra film margin.
        usable_width = self._film_width_mm
        for file_path, items in self._artwork_items.items():
            artwork_rectangles = []
            width_mm, height_mm = self._artwork_sizes[file_path]
            if width_mm > usable_width:
                scale = usable_width / width_mm
                width_mm *= scale
                height_mm *= scale
            for item in items:
                rotation = int(item.data(0) or 0)
                item_width, item_height = (width_mm, height_mm)
                if not self._group_repetitions and rotation % 2:
                    item_width, item_height = height_mm, width_mm
                artwork_rectangles.append((item, item_width, item_height))
            artwork_rectangles.sort(key=lambda entry: (entry[2], entry[1]), reverse=True)
            grouped_rectangles.append(artwork_rectangles)

        if self._group_repetitions:
            variant = max(0, self._regroup_variant)
            sorters = (
                lambda group: (len(group), group[0][1] * group[0][2]),
                lambda group: (group[0][1] * group[0][2], len(group)),
                lambda group: (max(group[0][1], group[0][2]), len(group)),
                lambda group: (group[0][2], group[0][1]),
            )
            grouped_rectangles.sort(key=sorters[variant % len(sorters)], reverse=True)
            small_limit = usable_width * 0.25
            large_groups = [
                group for group in grouped_rectangles
                if group and max(group[0][1], group[0][2]) > small_limit
            ]
            small_groups = [
                group for group in grouped_rectangles
                if group and max(group[0][1], group[0][2]) <= small_limit
            ]
            # Equal arts remain consecutive. Small groups are considered last,
            # but can occupy genuine holes left by the large groups.
            grouped_rectangles = large_groups + small_groups
            rectangles = [rectangle for group in grouped_rectangles for rectangle in group]
        else:
            rectangles = [rectangle for group in grouped_rectangles for rectangle in group]
            # First-fit decreasing height keeps packing fast even with thousands of copies.
            rectangles.sort(key=lambda entry: (entry[2], entry[1]), reverse=True)
        if self._group_repetitions:
            layout = self._maxrects_grouped_positions(
                [[(width, height) for _, width, height in group]
                 for group in grouped_rectangles],
                usable_width,
                self._gap_mm,
                variant,
            )
        else:
            positions = self._best_fit_positions(
                [(width, height) for _, width, height in rectangles], usable_width, self._gap_mm
            )
            layout = [(x, y, False) for x, y in positions]
        used_height = 0.0
        for (item, width_mm, height_mm), (local_x, local_y, auto_rotated) in zip(rectangles, layout):
            if self._group_repetitions:
                current_rotated = bool(int(item.data(0) or 0) % 2)
                if current_rotated != auto_rotated:
                    item.setPixmap(item.pixmap().transformed(
                        QTransform().rotate(90), Qt.TransformationMode.SmoothTransformation
                    ))
                    item.setData(0, (int(item.data(0) or 0) + 1) % 4)
                if auto_rotated:
                    width_mm, height_mm = height_mm, width_mm
            item.setTransform(self._physical_transform(item.pixmap(), width_mm, height_mm))
            item.setPos(local_x, local_y)
            used_height = max(used_height, local_y + height_mm)

        if self._roll_outline is None:
            self._draw_roll_outline()
        self._roll_outline.setRect(0, 0, self._film_width_mm, used_height)
        self.setSceneRect(0, 0, self._film_width_mm, used_height)
        self.used_length_changed.emit(used_height / 1000.0)

    @staticmethod
    def _best_fit_positions(
        sizes: list[tuple[float, float]], usable_width: float, gap: float
    ) -> list[tuple[float, float]]:
        """Pack rectangles into horizontal shelves using a scalable best fit."""
        rows: list[dict[str, float]] = []
        positions: list[tuple[float, float]] = []
        for width, height in sizes:
            best_row = None
            best_remaining_width = float("inf")
            for row in rows:
                next_x = row["used_width"] + gap
                remaining_width = usable_width - (next_x + width)
                if height <= row["height"] + 1e-6 and remaining_width >= -1e-6:
                    if remaining_width < best_remaining_width:
                        best_row = row
                        best_remaining_width = remaining_width

            if best_row is None:
                y = rows[-1]["y"] + rows[-1]["height"] + gap if rows else 0.0
                best_row = {"y": y, "height": height, "used_width": 0.0}
                rows.append(best_row)
                x = 0.0
            else:
                x = best_row["used_width"] + gap

            positions.append((x, best_row["y"]))
            best_row["used_width"] = x + width
        return positions

    @staticmethod
    def _best_fit_oriented_positions(
        sizes: list[tuple[float, float]], usable_width: float, gap: float
    ) -> list[tuple[float, float, bool]]:
        """Shelf packing that may rotate each rectangle to reduce roll length."""
        rows: list[dict[str, float]] = []
        positions: list[tuple[float, float, bool]] = []
        for original_width, original_height in sizes:
            orientations = [(original_width, original_height, False)]
            if abs(original_width - original_height) > 1e-6 and original_height <= usable_width:
                orientations.append((original_height, original_width, True))

            if not rows:
                width, height, rotated = min(
                    orientations,
                    key=lambda value: (
                        value[1] / max(1, int((usable_width + gap) // (value[0] + gap))),
                        value[1],
                    ),
                )
                rows.append({"y": 0.0, "height": height, "used_width": width})
                positions.append((0.0, 0.0, rotated))
                continue

            candidates = []
            current_height = rows[-1]["y"] + rows[-1]["height"] if rows else 0.0
            for row_index, row in enumerate(rows):
                for width, height, rotated in orientations:
                    x = row["used_width"] + gap
                    if height <= row["height"] + 1e-6 and x + width <= usable_width + 1e-6:
                        candidates.append((current_height, usable_width - x - width, row["y"], x,
                                           row_index, width, height, rotated))

            new_y = current_height + (gap if rows else 0.0)
            for width, height, rotated in orientations:
                if width <= usable_width + 1e-6:
                    candidates.append((new_y + height, usable_width - width, new_y, 0.0,
                                       len(rows), width, height, rotated))

            _, _, y, x, row_index, width, height, rotated = min(candidates)
            if row_index == len(rows):
                rows.append({"y": y, "height": height, "used_width": width})
            else:
                rows[row_index]["used_width"] = x + width
            positions.append((x, y, rotated))
        return positions

    @staticmethod
    def _maxrects_grouped_positions(
        groups: list[list[tuple[float, float]]], usable_width: float, gap: float,
        variant: int = 0,
    ) -> list[tuple[float, float, bool]]:
        """Two-dimensional packing with equal artworks processed consecutively."""
        if not groups:
            return []
        oriented_groups = []
        height_bound = 0.0
        for group in groups:
            if not group:
                continue
            width, height = group[0]
            choices = [(width, height, False)]
            if height <= usable_width and abs(width - height) > 1e-6:
                choices.append((height, width, True))
            ranked_choices = sorted(
                choices,
                key=lambda value: (
                    ((len(group) + max(1, int((usable_width + gap) // (value[0] + gap))) - 1)
                     // max(1, int((usable_width + gap) // (value[0] + gap)))) * (value[1] + gap),
                    value[1],
                ),
            )
            chosen = ranked_choices[(variant // 2) % len(ranked_choices)]
            oriented_groups.append((group, chosen))
            height_bound += len(group) * (chosen[1] + gap)

        bin_width = usable_width + gap
        free = [(0.0, 0.0, bin_width, max(height_bound, 1.0))]
        result: list[tuple[float, float, bool]] = []
        for group, (width, height, rotated) in oriented_groups:
            for _ in group:
                packed_width, packed_height = width + gap, height + gap
                candidates = []
                for index, (free_x, free_y, free_width, free_height) in enumerate(free):
                    if packed_width <= free_width + 1e-6 and packed_height <= free_height + 1e-6:
                        candidates.append((
                            free_y + packed_height,
                            free_x,
                            min(free_width - packed_width, free_height - packed_height),
                            free_width * free_height - packed_width * packed_height,
                            index,
                        ))
                if not candidates:
                    # The bound is intentionally generous; this is a safe fallback
                    # for unexpected floating-point edge cases.
                    used_bottom = max((y + h for x, y, w, h in free), default=0.0)
                    free.append((0.0, used_bottom, bin_width, packed_height))
                    candidates.append((used_bottom + packed_height, 0.0, 0.0, 0.0, len(free) - 1))
                _, _, _, _, selected = min(candidates)
                x, y, _, _ = free[selected]
                used = (x, y, packed_width, packed_height)
                free = RollView._split_free_rectangles(free, used)
                visible_x = usable_width - x - width if variant % 2 else x
                result.append((visible_x, y, rotated))
        return result

    @staticmethod
    def _split_free_rectangles(free, used):
        used_x, used_y, used_width, used_height = used
        used_right, used_bottom = used_x + used_width, used_y + used_height
        split = []
        for x, y, width, height in free:
            right, bottom = x + width, y + height
            if used_right <= x or used_x >= right or used_bottom <= y or used_y >= bottom:
                split.append((x, y, width, height))
                continue
            if used_x > x:
                split.append((x, y, used_x - x, height))
            if used_right < right:
                split.append((used_right, y, right - used_right, height))
            if used_y > y:
                split.append((x, y, width, used_y - y))
            if used_bottom < bottom:
                split.append((x, used_bottom, width, bottom - used_bottom))
        split = [rect for rect in split if rect[2] > 1e-6 and rect[3] > 1e-6]
        return [
            rect for index, rect in enumerate(split)
            if not any(
                index != other_index
                and (rect != other or other_index < index)
                and rect[0] >= other[0] - 1e-6 and rect[1] >= other[1] - 1e-6
                and rect[0] + rect[2] <= other[0] + other[2] + 1e-6
                and rect[1] + rect[3] <= other[1] + other[3] + 1e-6
                for other_index, other in enumerate(split)
            )
        ]

    @staticmethod
    def _physical_transform(pixmap: QPixmap, width_mm: float, height_mm: float) -> QTransform:
        return QTransform.fromScale(width_mm / pixmap.width(), height_mm / pixmap.height())

    def fit_roll(self) -> None:
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()
        self._position_action_bar()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_action_bar()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._position_action_bar()

    @property
    def zoom_percent(self) -> int:
        return round(self._zoom * 100)

    def wheelEvent(self, event):
        self.set_zoom(self._zoom * (1.1 if event.angleDelta().y() > 0 else 0.9))
        event.accept()

    def mousePressEvent(self, event) -> None:
        clicked_item = self.itemAt(event.position().toPoint())
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not isinstance(clicked_item, QGraphicsPixmapItem)
        ):
            self.scene().clearSelection()
            self._is_panning = True
            self._pan_start = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._is_panning and self._pan_start is not None:
            current_position = event.position().toPoint()
            movement = current_position - self._pan_start
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - movement.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - movement.y()
            )
            self._pan_start = current_position
            event.accept()
            return
        super().mouseMoveEvent(event)
        self._position_action_bar()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_panning:
            self._is_panning = False
            self._pan_start = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._finalize_manual_positions()

    def _finalize_manual_positions(self) -> None:
        artwork_items = [
            item
            for items in self._artwork_items.values()
            for item in items
        ]
        if not artwork_items:
            return
        for item in self.scene().selectedItems():
            if not isinstance(item, QGraphicsPixmapItem):
                continue
            bounds = item.sceneBoundingRect()
            move_x = 0.0
            move_y = 0.0
            if bounds.left() < 0:
                move_x = -bounds.left()
            elif bounds.right() > self._film_width_mm:
                move_x = self._film_width_mm - bounds.right()
            if bounds.top() < 0:
                move_y = -bounds.top()
            item.moveBy(move_x, move_y)

        used_height = max(item.sceneBoundingRect().bottom() for item in artwork_items)
        used_height = max(0.0, used_height)
        if self._roll_outline is None:
            self._draw_roll_outline()
        self._roll_outline.setRect(0, 0, self._film_width_mm, used_height)
        self.setSceneRect(0, 0, self._film_width_mm, used_height)
        self.used_length_changed.emit(used_height / 1000.0)
        self._position_action_bar()
