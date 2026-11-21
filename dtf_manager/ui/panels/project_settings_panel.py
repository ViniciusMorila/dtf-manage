from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QComboBox, QCheckBox, QProgressBar, QScrollArea, QWidget

from dtf_manager.core.constants import DEFAULT_COST_PER_METER, DEFAULT_DPI, DEFAULT_FILM_WIDTH_MM, DEFAULT_GAP_MM, DEFAULT_ROLL_LENGTH_M
from dtf_manager.ui.widgets.dimension_spinbox import EditableDoubleSpinBox


class ProjectSettingsPanel(QFrame):
    export_requested = Signal()
    finalize_requested = Signal()
    folder_selected = Signal(Path)
    roll_settings_changed = Signal(float, float, float)
    regroup_requested = Signal()
    add_artwork_requested = Signal()
    import_orders_requested = Signal()
    link_memory_requested = Signal()
    continue_operation_requested = Signal()
    cancel_operation_requested = Signal()
    finalize_operation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._settings = QSettings("DTF Manager", "DTF Manager")
        saved_folder = self._settings.value("artwork_folder", "", type=str)
        saved_path = Path(saved_folder) if saved_folder else None
        self._folder_path = saved_path if saved_path and saved_path.is_dir() else None
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("sidebarContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        title = QLabel("CONFIGURACOES DO PROJETO")
        title.setObjectName("eyebrow")
        layout.addWidget(title)
        self.active_operation_card = QFrame()
        self.active_operation_card.setObjectName("activeOperationCard")
        active_layout = QVBoxLayout(self.active_operation_card)
        active_title = QLabel("OPERAÇÃO EM ANDAMENTO")
        active_title.setObjectName("panelTitle")
        active_layout.addWidget(active_title)
        self.active_operation_summary = QLabel("")
        self.active_operation_summary.setObjectName("muted")
        self.active_operation_summary.setWordWrap(True)
        active_layout.addWidget(self.active_operation_summary)
        continue_operation = QPushButton("CONTINUAR")
        continue_operation.setObjectName("primaryButton")
        continue_operation.clicked.connect(self.continue_operation_requested)
        active_layout.addWidget(continue_operation)
        end_row = QHBoxLayout()
        end_row.setSpacing(8)
        self.cancel_operation_button = QPushButton("CANCELAR")
        self.cancel_operation_button.setObjectName("removeButton")
        self.cancel_operation_button.setToolTip(
            "Descarta esta planilha: você poderá carregá-la de novo e começar do zero.")
        self.cancel_operation_button.clicked.connect(self.cancel_operation_requested)
        self.finalize_operation_button = QPushButton("FINALIZAR")
        self.finalize_operation_button.setToolTip(
            "Encerra o trabalho: dá baixa no estoque de camisetas e zera o futuro.")
        self.finalize_operation_button.clicked.connect(self.finalize_operation_requested)
        end_row.addWidget(self.cancel_operation_button)
        end_row.addWidget(self.finalize_operation_button)
        active_layout.addLayout(end_row)
        self.active_operation_card.hide()
        layout.addWidget(self.active_operation_card)
        folder_title = QLabel("PASTA DAS ARTES")
        folder_title.setObjectName("panelTitle")
        layout.addWidget(folder_title)
        folder_row = QHBoxLayout()
        select = QPushButton("Selecionar pasta")
        select.clicked.connect(self._select_folder)
        refresh = QPushButton("Atualizar")
        refresh.setObjectName("iconButton")
        refresh.setToolTip("Atualizar artes")
        refresh.clicked.connect(self._refresh_folder)
        folder_row.addWidget(select, 1)
        folder_row.addWidget(refresh)
        layout.addLayout(folder_row)
        self.folder_label = QLabel(
            str(self._folder_path) if self._folder_path else "Nenhuma pasta selecionada"
        )
        self.folder_label.setObjectName("muted")
        self.folder_label.setWordWrap(True)
        layout.addWidget(self.folder_label)
        actions = QHBoxLayout()
        self.import_orders_button = QPushButton("IMPORT PEDIDO")
        self.import_orders_button.setObjectName("primaryButton")
        self.import_orders_button.clicked.connect(self.import_orders_requested)
        add_artwork = QPushButton("+  ADD ARTE")
        add_artwork.setObjectName("addButton")
        add_artwork.clicked.connect(self.add_artwork_requested)
        actions.addWidget(self.import_orders_button)
        actions.addWidget(add_artwork)
        layout.addLayout(actions)
        memory_button = QPushButton("MEMÓRIA DE VÍNCULOS")
        memory_button.clicked.connect(self.link_memory_requested)
        layout.addWidget(memory_button)
        global_title = QLabel("CONFIGURACOES GLOBAIS")
        global_title.setObjectName("panelTitle")
        layout.addWidget(global_title)
        width_card = QFrame()
        width_card.setObjectName("widthCard")
        width_layout = QVBoxLayout(width_card)
        width_layout.setContentsMargins(14, 12, 14, 12)
        width_caption = QLabel("LARGURA DO FILME")
        width_caption.setObjectName("eyebrow")
        width_layout.addWidget(width_caption)
        width_row = QHBoxLayout()
        self.width_input = EditableDoubleSpinBox()
        self.width_input.setRange(1, 2000)
        self.width_input.setValue(DEFAULT_FILM_WIDTH_MM / 10)
        self.width_input.setSuffix(" cm")
        self.width_input.setDecimals(2)
        self.width_input.setButtonSymbols(EditableDoubleSpinBox.ButtonSymbols.UpDownArrows)
        self.width_input.valueChanged.connect(self._emit_roll_settings)
        width_row.addWidget(self.width_input)
        width_layout.addLayout(width_row)
        width_hint = QLabel("Largura fisica do filme DTF")
        width_hint.setObjectName("muted")
        width_layout.addWidget(width_hint)
        layout.addWidget(width_card)
        self.cost_input = EditableDoubleSpinBox()
        self.cost_input.setRange(0, 9999)
        self.cost_input.setValue(DEFAULT_COST_PER_METER)
        self.cost_input.setPrefix("R$ ")
        self.cost_input.setDecimals(2)
        self.cost_input.setButtonSymbols(EditableDoubleSpinBox.ButtonSymbols.UpDownArrows)
        self.cost_input.valueChanged.connect(self._emit_roll_settings)
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["100", "150", "200", "300"])
        self.dpi_combo.setCurrentText("300")
        self.gap_combo = QComboBox()
        self.gap_combo.addItems(["0,3 cm", "0,5 cm", "1 cm", "2 cm", "3 cm"])
        self.gap_combo.setCurrentText("0,5 cm")
        self.gap_combo.currentIndexChanged.connect(self._emit_roll_settings)
        self.length_input = EditableDoubleSpinBox()
        self.length_input.setRange(1, 999)
        self.length_input.setValue(DEFAULT_ROLL_LENGTH_M)
        self.length_input.setSuffix(" m")
        self.length_input.setButtonSymbols(EditableDoubleSpinBox.ButtonSymbols.UpDownArrows)
        price_options = QHBoxLayout()
        price_options.setSpacing(8)
        price_column = QVBoxLayout()
        price_column.setSpacing(4)
        price_column.addLayout(
            self._label_with_info(
                "Preço R$",
                "Este é o valor que você paga por metro de DTF.",
            )
        )
        price_column.addWidget(self.cost_input)
        division_column = QVBoxLayout()
        division_column.setSpacing(4)
        division_column.addLayout(
            self._label_with_info(
                "Dividir metro",
                "Aqui você pode dividir o total do rolo em vários metros.",
            )
        )
        division_column.addWidget(self.length_input)
        price_options.addLayout(price_column, 1)
        price_options.addLayout(division_column, 1)
        layout.addLayout(price_options)

        print_options = QHBoxLayout()
        print_options.setSpacing(8)
        dpi_column = QVBoxLayout()
        dpi_column.setSpacing(4)
        dpi_label = QLabel("DPI")
        dpi_label.setObjectName("fieldLabel")
        dpi_column.addWidget(dpi_label)
        dpi_column.addWidget(self.dpi_combo)
        gap_column = QVBoxLayout()
        gap_column.setSpacing(4)
        gap_column.addLayout(
            self._label_with_info(
                "Gap",
                "Escolha o espaçamento que deseja entre uma estampa e outra.",
            )
        )
        gap_column.addWidget(self.gap_combo)
        print_options.addLayout(dpi_column, 1)
        print_options.addLayout(gap_column, 1)
        layout.addLayout(print_options)

        self.auto_split = QCheckBox("Divisao automatica")
        self.auto_split.setChecked(True)
        layout.addWidget(self.auto_split)
        split_hint = QLabel("O sistema dividira automaticamente o trabalho quando ultrapassar o comprimento maximo.")
        split_hint.setObjectName("muted")
        split_hint.setWordWrap(True)
        layout.addWidget(split_hint)
        layout.addStretch()
        regroup_row = QHBoxLayout()
        regroup_row.addStretch()
        self.regroup_button = QPushButton("REAGRUPAR")
        self.regroup_button.setObjectName("regroupButton")
        self.regroup_button.setFixedWidth(150)
        self.regroup_button.setToolTip("Agrupar artes repetidas e reorganizar o aproveitamento do filme")
        self.regroup_button.clicked.connect(self.regroup_requested)
        regroup_row.addWidget(self.regroup_button)
        regroup_row.addStretch()
        layout.addLayout(regroup_row)
        self.export_button = QPushButton("EXPORTAR DOCUMENTO  (.PNG)")
        self.export_button.setObjectName("exportButton")
        self.export_button.clicked.connect(self.export_requested)
        layout.addWidget(self.export_button)
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 100)
        self.export_progress.setValue(0)
        self.export_progress.setTextVisible(True)
        self.export_progress.hide()
        layout.addWidget(self.export_progress)
        self.export_status = QLabel("Exporta o rolo DTF sem fundo e salva na pasta Downloads.")
        self.export_status.setObjectName("muted")
        self.export_status.setWordWrap(True)
        layout.addWidget(self.export_status)
        self.finalize_button = QPushButton("FINALIZAR PEDIDO")
        self.finalize_button.setObjectName("finalizeButton")
        self.finalize_button.setToolTip(
            "Desconta do estoque de camisetas o que os pedidos importados consomem.")
        self.finalize_button.setEnabled(False)
        self.finalize_button.clicked.connect(self.finalize_requested)
        layout.addWidget(self.finalize_button)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    @staticmethod
    def _label_with_info(text: str, tooltip: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        info = QLabel("i")
        info.setObjectName("infoIcon")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setFixedSize(18, 18)
        info.setCursor(Qt.CursorShape.WhatsThisCursor)
        info.setToolTip(tooltip)
        row.addWidget(label)
        row.addWidget(info)
        row.addStretch()
        return row

    def _emit_roll_settings(self) -> None:
        self.roll_settings_changed.emit(
            self.width_input.value() * 10,
            self.gap_mm,
            self.cost_input.value(),
        )

    @property
    def gap_mm(self) -> float:
        gap_text = self.gap_combo.currentText().replace(",", ".").split()[0]
        return float(gap_text) * 10

    def set_finalize_enabled(self, enabled: bool) -> None:
        """Enabled only while there is a futuro to deduct and nothing is running."""
        self.finalize_button.setEnabled(bool(enabled))

    def start_export(self) -> None:
        self.export_button.hide()
        self.export_progress.setValue(0)
        self.export_progress.show()
        self.export_status.setText("Renderizando projeto... 0%")

    def update_export_progress(self, value: int, stage: str) -> None:
        self.export_progress.setValue(value)
        self.export_status.setText(f"{stage}... {value}%")

    def finish_export(self, output_paths: list[Path]) -> None:
        self.export_progress.hide()
        self.export_button.show()
        if len(output_paths) == 1:
            message = f"Download completado: {output_paths[0].name}"
        else:
            message = f"Exportação concluída: {len(output_paths)} arquivos salvos em Downloads."
        self.export_status.setText(message)

    def fail_export(self, message: str) -> None:
        self.export_progress.hide()
        self.export_button.show()
        self.export_status.setText(f"Falha ao exportar: {message}")

    def _select_folder(self) -> None:
        initial_folder = self._folder_path or Path.home()
        folder = QFileDialog.getExistingDirectory(self, "Selecionar pasta das artes", str(initial_folder))
        if folder:
            self._folder_path = Path(folder)
            self._settings.setValue("artwork_folder", str(self._folder_path))
            self.folder_label.setText(str(self._folder_path))
            self.folder_selected.emit(self._folder_path)

    def _refresh_folder(self) -> None:
        if self._folder_path and self._folder_path.is_dir():
            self.folder_label.setText(str(self._folder_path))
            self.folder_selected.emit(self._folder_path)
            return
        self._folder_path = None
        self._settings.remove("artwork_folder")
        self.folder_label.setText("Nenhuma pasta selecionada")

    @property
    def folder_path(self) -> Path | None:
        return self._folder_path

    def set_importing(self, importing: bool) -> None:
        self.import_orders_button.setEnabled(not importing)
        self.import_orders_button.setText("Importando pedidos..." if importing else "IMPORT PEDIDO")

    def set_active_operation(self, summary: str | None) -> None:
        self.active_operation_summary.setText(summary or "")
        self.active_operation_card.setVisible(bool(summary))
