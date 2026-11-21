from dtf_manager.core import auth_timing
from dataclasses import replace
from pathlib import Path
import sys
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QCoreApplication, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QStackedWidget, QTabWidget, QVBoxLayout, QWidget

from dtf_manager.core.constants import APP_NAME
from dtf_manager.ui.panels.artwork_panel import ArtworkPanel
from dtf_manager.ui.panels.project_settings_panel import ProjectSettingsPanel
from dtf_manager.ui.styles import APP_STYLE
from dtf_manager.ui.widgets.roll_view import RollView
from dtf_manager.ui.widgets.artwork_setup_dialog import ArtworkSetupDialog
from dtf_manager.services.export_service import ExportService
from dtf_manager.state.order_import_state import OrderImportState
from dtf_manager.ui.pages.orders_dashboard import OrdersDashboard
from dtf_manager.services.art_directory_scanner import ArtDirectoryError, scan_art_directory
from dtf_manager.services.automatic_art_linker import auto_link_orders
from dtf_manager.ui.widgets.automatic_link_summary_dialog import AutomaticLinkSummaryDialog
from dtf_manager.ui.pages.manual_linking_page import ManualLinkingPage
from dtf_manager.state.order_selectors import get_unlinked_items
from dtf_manager.services.print_plan_service import (
    PrintPlanValidationError, build_dtf_print_plan, prepare_print_plan_for_roll,
)
from dtf_manager.services.link_memory_repository import SqliteProductLinkMemoryRepository
from dtf_manager.services.link_memory_service import ArtLinkMemoryService
from dtf_manager.ui.pages.link_memory_page import LinkMemoryPage
from dtf_manager.ui.pages.production_review_page import ProductionReviewPage
from dtf_manager.models.print_plan import DTFOrderPlan
from dtf_manager.models.production_history import BatchRollSettingsSnapshot
from dtf_manager.services.production_history_repository import ProductionHistoryRepository, ProductionHistoryStorageError
from dtf_manager.services.production_history_service import create_production_batch_snapshot
from dtf_manager.ui.pages.production_history_page import ProductionHistoryPage
from dtf_manager.services.import_history_analyzer import analyze_imported_orders_against_history
from dtf_manager.services.active_operation_repository import ActiveOperationStorageError
from dtf_manager.services.sqlite_active_operation_repository import SqliteActiveOperationRepository
from dtf_manager.services.sqlite_database import DTFDatabase
from dtf_manager.services.processed_order_repository import ProcessedOrderRepository
from dtf_manager.services.active_operation_service import (
    build_import_operation_fingerprint, checkpoint_operation, create_active_operation,
)
from dtf_manager.ui.widgets.existing_operation_dialog import ExistingOperationDialog
from dtf_manager.core.stock_controller import StockController
from dtf_manager.services.stock_repository import StockRepository
from dtf_manager.services.stock_service import StockService
from dtf_manager.ui.pages.stock_tab import StockTab
from dtf_manager.ui.widgets.stock_dialogs import StockPrompts


def _days_text(days):
    if days is None:
        return "sem prazo"
    return f"{days} dia" + ("" if days == 1 else "s")


class MainWindow(QMainWindow):
    logout_requested = Signal()
    renew_requested = Signal()
    subscribe_requested = Signal()
    plans_requested = Signal()   # optional site (DTF_PAYMENT_URL)

    def __init__(self):
        super().__init__()
        QCoreApplication.setOrganizationName("DTF Manager")
        QCoreApplication.setApplicationName("DTF Manager")
        self.setWindowTitle(APP_NAME)
        self.resize(1600, 900)
        self.setMinimumSize(1280, 720)
        self.order_import_state = OrderImportState()
        self.database = DTFDatabase.default()
        self.link_memory_repository = SqliteProductLinkMemoryRepository.default(self.database)
        self.link_memory_service = ArtLinkMemoryService(self.link_memory_repository)
        self.production_history_repository = ProductionHistoryRepository.default()
        self.processed_order_repository = ProcessedOrderRepository.default(self.database)
        self.processed_order_repository.migrate_history(self.production_history_repository.list_all())
        self.active_operation_repository = SqliteActiveOperationRepository.default(self.database)
        self.active_operation = self.active_operation_repository.load_active()
        self._restoring_operation = False
        self._is_importing_orders = False
        self._is_auto_linking = False
        self._is_building_order = False
        self._return_to_production_review = False
        self._pending_stock_import = None
        with auth_timing.span("main_build_ui"):
            self._build_ui()
        self._authentication_logout = False
        self._build_license_status()
        self.order_import_state.changed.connect(self._checkpoint_current_operation)
        self._refresh_active_operation_card()
        if self.link_memory_repository.load_warning:
            self.statusBar().showMessage(self.link_memory_repository.load_warning, 15000)
        elif self.production_history_repository.load_warning:
            self.statusBar().showMessage(self.production_history_repository.load_warning, 15000)
        elif self.active_operation_repository.load_warning:
            self.statusBar().showMessage(self.active_operation_repository.load_warning, 15000)

    def _build_license_status(self):
        """Top right corner: plan and days left, greeting, account menu and sign out."""
        self.license_label = QLabel()
        self.license_label.setObjectName("licenseLabel")
        self.license_label.setTextFormat(Qt.TextFormat.PlainText)
        self.license_label.hide()
        self.greeting_label = QLabel()
        self.greeting_label.setObjectName("greetingLabel")
        self.greeting_label.setTextFormat(Qt.TextFormat.PlainText)
        self.greeting_label.hide()
        self.account_button = QPushButton("Conta")
        menu = QMenu(self.account_button)
        self.subscribe_action = menu.addAction("Assinar...")
        self.renew_action = menu.addAction("Renovar licença (inserir chave)...")
        self.plans_action = menu.addAction("Ver planos no site...")
        self.plans_action.setVisible(False)
        self.subscribe_action.triggered.connect(self.subscribe_requested)
        self.renew_action.triggered.connect(self.renew_requested)
        self.plans_action.triggered.connect(self.plans_requested)
        self.account_button.setMenu(menu)
        self.logout_button = QPushButton("Sair da conta")
        self.logout_button.clicked.connect(self.logout_requested)
        corner = self._corner = QWidget(self.menuBar())
        row = QHBoxLayout(corner)
        row.setContentsMargins(8, 4, 12, 4)
        row.setSpacing(10)
        self._first_name = ""
        self._license_info = None
        self._offline_remaining = None
        for widget in (self.greeting_label, self.license_label, self.account_button,
                       self.logout_button):
            row.addWidget(widget)
        self.menuBar().setCornerWidget(corner, Qt.Corner.TopRightCorner)

    def set_user_name(self, name):
        """First name for the greeting; unknown means no greeting."""
        first = (name or "").split(maxsplit=1)
        self._first_name = first[0][:40] if first else ""
        self._render_account_header()

    def set_payment_site(self, available):
        self.plans_action.setVisible(available)

    def show_license_notice(self, text):
        """Discreet, temporary notice in the status bar (never blocks the work)."""
        self.statusBar().showMessage(text, 30000)

    def set_license_state(self, info, offline_remaining=None):
        """Show plan and days left. Called by the controller after each validation."""
        self._license_info = info
        self._offline_remaining = offline_remaining
        self._render_account_header()

    def _render_account_header(self):
        """"Olá, Nome (Plano)" first, then the days left; the trial keeps its own message.

        Without a known name the label keeps the full "Plano X: ..." text instead."""
        info, offline_remaining, name = (self._license_info, self._offline_remaining,
                                         self._first_name)
        greeting = f"Olá, {name}" if name else ""
        if info is not None and name and info.plano != "TESTE":
            greeting += f" ({info.plan_name})"
        self.greeting_label.setText(greeting)
        self.greeting_label.setVisible(bool(greeting))
        if info is None:
            self.license_label.hide()
            return
        days = info.dias_restantes
        tone = "normal"
        short = bool(name) and info.plano != "TESTE"       # the plan is already in the greeting
        if info.vitalicia:
            text = "" if short else f"Plano {info.plan_name}"
        elif info.plano == "TESTE":
            text = f"Período de teste: faltam {_days_text(days)}"
            tone = "trial"
        else:
            text = f"{_days_text(days)} restantes" if short else (
                f"Plano {info.plan_name}: {_days_text(days)} restantes")
            if days is not None and days <= 7:
                text = (f"vence em {_days_text(days)}" if short
                        else f"Plano {info.plan_name}: vence em {_days_text(days)}")
                tone = "warning"
        if offline_remaining is not None:
            hours = max(int(offline_remaining.total_seconds() // 3600), 0)
            text = (f"Modo offline: licença não validada. Carência restante: {hours // 24} dia(s) "
                    f"e {hours % 24} h. Conecte-se à internet." + (f" | {text}" if text else ""))
            tone = "offline"
        self.license_label.setText(text)
        self.license_label.setToolTip(
            "Validade: " + (info.data_expiracao[:10] if info.data_expiracao else "sem expiração"))
        self.license_label.setProperty("tone", tone)
        self.license_label.style().unpolish(self.license_label)
        self.license_label.style().polish(self.license_label)
        self.license_label.setVisible(bool(text))

    def save_for_license_lock(self):
        """Persist the active operation before the license blocks the window."""
        try:
            self._checkpoint_current_operation()
        except Exception:
            self.statusBar().showMessage("Não foi possível salvar a operação automaticamente.", 15000)
            return False
        return True

    def _build_main_tabs(self):
        """DTF (the existing pages, unchanged) + the two stock tabs."""
        self.main_tabs = QTabWidget()
        self.main_tabs.setObjectName("mainTabs")
        self.main_tabs.setDocumentMode(False)      # the QSS centers the tab bar
        self.main_tabs.addTab(self.pages, "DTF")
        self.stock_tab = StockTab()
        self.stock_controller = StockController(
            StockService(StockRepository.default(self.database)), StockPrompts(self),
            self.stock_tab, mounted_lookup=self.processed_order_repository.known_orders,
            parent=self)
        self.main_tabs.addTab(self.stock_tab, "Estoque de camisetas")
        prints = QLabel("Em breve")
        prints.setObjectName("emptyState")
        prints.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prints_tab = prints
        self.main_tabs.addTab(prints, "Estoque de estampas")
        self.setCentralWidget(self.main_tabs)

    def _build_ui(self):
        self.pages = QStackedWidget()
        self._build_main_tabs()
        root = QWidget()
        root.setObjectName("appRoot")
        self.editor_page = root
        self.pages.addWidget(root)
        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(14)
        settings = ProjectSettingsPanel()
        self.settings = settings
        self.export_service = ExportService()
        self._export_stage = 0
        self._export_progress = 0
        self._export_timer = QTimer(self)
        self._export_timer.setInterval(35)
        self._export_timer.timeout.connect(self._advance_export)
        settings.setFixedWidth(330)
        settings.export_requested.connect(self._start_export)
        settings.regroup_requested.connect(lambda: self.roll_view.regroup_artworks())
        settings.add_artwork_requested.connect(lambda: self._add_artwork(artwork, settings.folder_path))
        settings.import_orders_requested.connect(self._import_orders)
        settings.finalize_requested.connect(self.stock_controller.finalize)
        self.stock_controller.changed.connect(settings.set_finalize_enabled)
        settings.set_finalize_enabled(self.stock_controller.has_future)
        settings.link_memory_requested.connect(self._open_link_memory)
        settings.continue_operation_requested.connect(self._continue_active_operation)
        settings.cancel_operation_requested.connect(self._cancel_active_operation)
        settings.finalize_operation_requested.connect(self._finalize_active_operation)
        main_layout.addWidget(settings)
        main_layout.addWidget(self._build_roll_area(), 1)
        artwork = ArtworkPanel()
        self.artwork_panel = artwork
        # Keep enough room for the artwork controls while allowing a 57 cm roll
        # to be shown completely at 100% on common 1366 px displays.
        artwork.setFixedWidth(375)
        settings.folder_selected.connect(lambda folder: self._set_artwork_folder(artwork, folder))
        artwork.artwork_added.connect(
            lambda file_path, width, height, quantity: self._add_to_roll(
                str(file_path), width * 10, height * 10, quantity
            )
        )
        artwork.artwork_dimensions_changed.connect(
            lambda file_path, width, height: self.roll_view.update_artwork(str(file_path), width * 10, height * 10)
        )
        artwork.artwork_quantity_changed.connect(
            lambda file_path, quantity: self.roll_view.update_artwork_quantity(str(file_path), quantity)
        )
        artwork.artwork_removed.connect(self._remove_from_roll)
        artwork.artwork_selection_requested.connect(
            lambda file_path: self.roll_view.select_artwork(str(file_path))
        )
        self.roll_view.used_length_changed.connect(artwork.set_used_meters)
        self.roll_view.used_length_changed.connect(self._update_used_length)
        self.roll_view.selected_copy_removed.connect(
            lambda file_path, quantity: artwork.set_quantity_from_roll(Path(file_path), quantity)
        )
        settings.roll_settings_changed.connect(
            lambda width_mm, gap_mm, cost: self._update_roll_settings(artwork, width_mm, gap_mm, cost)
        )
        self._update_roll_settings(
            artwork,
            settings.width_input.value() * 10,
            settings.gap_mm,
            settings.cost_input.value(),
        )
        if settings.folder_path:
            self._set_artwork_folder(artwork, settings.folder_path)
        main_layout.addWidget(artwork)
        self.orders_dashboard = OrdersDashboard(self.order_import_state)
        self.orders_dashboard.back_requested.connect(lambda: self.pages.setCurrentWidget(self.editor_page))
        self.orders_dashboard.import_requested.connect(self._import_orders)
        self.orders_dashboard.automatic_link_requested.connect(self._automatic_link_orders)
        self.orders_dashboard.manual_link_requested.connect(self._open_manual_queue)
        self.orders_dashboard.item_edit_requested.connect(self._open_manual_item)
        self.orders_dashboard.build_order_requested.connect(self._build_imported_order_roll)
        self.pages.addWidget(self.orders_dashboard)
        self.manual_linking_page = ManualLinkingPage(
            self.order_import_state, self.link_memory_service
        )
        self.manual_linking_page.set_artwork_folder(settings.folder_path)
        settings.folder_selected.connect(self.manual_linking_page.set_artwork_folder)
        self.manual_linking_page.back_requested.connect(self._leave_manual_linking)
        self.manual_linking_page.session_completed.connect(self._finish_manual_session)
        self.manual_linking_page.checkpoint_requested.connect(
            lambda: self._checkpoint_current_operation("manual_linking")
        )
        self.pages.addWidget(self.manual_linking_page)
        self.production_review_page = ProductionReviewPage(self.order_import_state)
        self.production_review_page.back_requested.connect(
            lambda: self.pages.setCurrentWidget(self.orders_dashboard)
        )
        self.production_review_page.correction_requested.connect(self._correct_from_review)
        self.production_review_page.mount_requested.connect(self._apply_reviewed_plan)
        self.pages.addWidget(self.production_review_page)
        self.link_memory_page = LinkMemoryPage(self.link_memory_repository)
        self.link_memory_page.back_requested.connect(
            lambda: self.pages.setCurrentWidget(self.editor_page)
        )
        self.pages.addWidget(self.link_memory_page)
        self.production_history_page = ProductionHistoryPage(self.production_history_repository)
        self.production_history_page.back_requested.connect(
            lambda: self.pages.setCurrentWidget(self.editor_page)
        )
        self.pages.addWidget(self.production_history_page)

    def _open_link_memory(self) -> None:
        self.link_memory_page.refresh()
        self.pages.setCurrentWidget(self.link_memory_page)

    def _current_operation_stage(self) -> str:
        current = self.pages.currentWidget()
        if current is self.manual_linking_page:
            return "manual_linking"
        if current is self.production_review_page:
            return "production_review"
        return "orders_dashboard"

    def _checkpoint_current_operation(self, stage: str | None = None) -> None:
        if self._restoring_operation or self.active_operation is None:
            return
        selected_stage = stage or self._current_operation_stage()
        manual_state = (
            self.manual_linking_page.session_snapshot()
            if selected_stage == "manual_linking" else self.active_operation.manual_linking_state
        )
        self.active_operation = checkpoint_operation(
            self.active_operation,
            self.order_import_state.imported_orders,
            selected_stage,
            manual_state,
        )
        try:
            self.active_operation_repository.save_active(self.active_operation)
        except ActiveOperationStorageError as error:
            self.statusBar().showMessage(str(error), 15000)
        self._refresh_active_operation_card()

    def _refresh_active_operation_card(self) -> None:
        if not hasattr(self, "settings"):
            return
        operation = self.active_operation
        if operation is None:
            self.settings.set_active_operation(None)
            return
        from datetime import datetime

        meta = operation.metadata
        updated = datetime.fromisoformat(operation.updated_at.replace("Z", "+00:00")).astimezone()
        self.settings.set_active_operation(
            f"{meta.order_count} pedidos\n{meta.linked_count} vinculados · "
            f"{meta.unlinked_count} não vinculados\nAtualizado em {updated:%d/%m/%Y %H:%M}"
        )

    def _continue_active_operation(self) -> None:
        if self.active_operation is None:
            return
        operation = self.active_operation
        self._pending_stock_import = None
        self._restoring_operation = True
        try:
            self.order_import_state.replace_orders(list(operation.imported_orders))
        finally:
            self._restoring_operation = False
        self.stock_controller.sync_loaded_orders(operation.imported_orders)
        if operation.workflow_stage == "manual_linking" and operation.manual_linking_state:
            self.pages.setCurrentWidget(self.manual_linking_page)
            if self.manual_linking_page.restore_session(operation.manual_linking_state):
                return
        if operation.workflow_stage in {"production_review", "ready_to_mount"}:
            self._build_imported_order_roll()
            return
        self.pages.setCurrentWidget(self.orders_dashboard)

    def _activate_new_operation(self, orders, fingerprint: str, source_file_name: str) -> None:
        self.active_operation = create_active_operation(orders, fingerprint, source_file_name)
        self._restoring_operation = True
        try:
            self.order_import_state.replace_orders(list(orders))
        finally:
            self._restoring_operation = False
        try:
            self.active_operation_repository.save_active(self.active_operation)
        except ActiveOperationStorageError as error:
            QMessageBox.warning(self, "Operação em andamento", str(error))
        self._refresh_active_operation_card()
        self.pages.setCurrentWidget(self.orders_dashboard)
        decision, self._pending_stock_import = self._pending_stock_import, None
        if decision is not None:
            self.stock_controller.apply_import(decision)

    def _end_active_operation(self) -> None:
        """Forgets the active operation and the orders loaded for it (project back to empty)."""
        self.active_operation_repository.clear_active()
        self.active_operation = None
        self._restoring_operation = True
        try:
            self.order_import_state.replace_orders([])
        finally:
            self._restoring_operation = False
        self._pending_stock_import = None
        self._refresh_active_operation_card()
        self.pages.setCurrentWidget(self.editor_page)

    def _cancel_active_operation(self) -> None:
        """Cancel: drops this spreadsheet's work so it can be imported again from zero."""
        operation = self.active_operation
        if operation is None:
            return
        answer = QMessageBox.question(
            self, "Cancelar operação",
            f"Cancelar esta operação ({operation.metadata.order_count} pedidos)?\n\n"
            "Os pedidos saem do projeto, os vínculos feitos nela são descartados e o futuro de "
            "camisetas dessa planilha é zerado. O estoque não muda. Você poderá importar a "
            "planilha de novo e começar do zero.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._end_active_operation()
        except ActiveOperationStorageError as error:
            QMessageBox.warning(self, "Operação em andamento", str(error))
            return
        self.stock_controller.cancel_import()
        self.statusBar().showMessage(
            "Operação cancelada. Você pode importar a planilha de novo.", 9000)

    def _finalize_active_operation(self) -> None:
        """Finalize: deducts the shirts from the stock, zeroes the futuro and closes the work."""
        if self.active_operation is None:
            return
        if self.stock_controller.has_future:
            if not self.stock_controller.finalize():
                return                                   # declined (or nothing was deducted)
        else:
            answer = QMessageBox.question(
                self, "Finalizar operação",
                "Não há camisetas no futuro para dar baixa no estoque. "
                "Finalizar mesmo assim e encerrar esta operação?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self._end_active_operation()
        except ActiveOperationStorageError as error:
            QMessageBox.warning(self, "Operação em andamento", str(error))
            return
        self.statusBar().showMessage("Operação finalizada e estoque atualizado.", 9000)

    def _open_production_history(self) -> None:
        self.production_history_page.pages.setCurrentIndex(0)
        self.production_history_page.refresh()
        self.pages.setCurrentWidget(self.production_history_page)

    def _open_manual_queue(self, start_item_id: str | None = None) -> None:
        if start_item_id is None and self.manual_linking_page.can_resume_queue():
            self.pages.setCurrentWidget(self.manual_linking_page)
            if self.manual_linking_page.resume_queue():
                self._checkpoint_current_operation("manual_linking")
                return
        if not get_unlinked_items(self.order_import_state.all_items):
            QMessageBox.information(
                self, "Vinculação manual", "Todos os produtos já estão vinculados."
            )
            return
        # Keep every imported item in the queue so its position remains based on
        # the original spreadsheet (for example 7/89), while the page skips the
        # items that are already linked.
        item_ids = tuple(item.id for item in self.order_import_state.all_items)
        self.pages.setCurrentWidget(self.manual_linking_page)
        self.manual_linking_page.start_queue(item_ids, start_item_id)
        self._checkpoint_current_operation("manual_linking")

    def _open_manual_item(self, item_id: str) -> None:
        item = self.order_import_state.find_item(item_id)
        if item is None:
            return
        if item.link_status == "unlinked":
            self._open_manual_queue(item_id)
        else:
            self.manual_linking_page.start_single(item_id)
            self.pages.setCurrentWidget(self.manual_linking_page)
            self._checkpoint_current_operation("manual_linking")

    def _correct_from_review(self, item_id: str) -> None:
        self._return_to_production_review = True
        self.manual_linking_page.start_single(item_id)
        self.pages.setCurrentWidget(self.manual_linking_page)
        self._checkpoint_current_operation("manual_linking")

    def _leave_manual_linking(self) -> None:
        if self._return_to_production_review:
            self._return_to_production_review = False
            self.pages.setCurrentWidget(self.production_review_page)
            self.production_review_page.revalidate()
            self._checkpoint_current_operation("production_review")
        else:
            self.pages.setCurrentWidget(self.orders_dashboard)
            self._checkpoint_current_operation("orders_dashboard")

    def _finish_manual_session(self, linked_count: int) -> None:
        self._return_to_production_review = False
        self.pages.setCurrentWidget(self.orders_dashboard)
        self._checkpoint_current_operation("orders_dashboard")
        remaining = len(get_unlinked_items(self.order_import_state.all_items))
        QMessageBox.information(
            self,
            "Vinculação manual concluída",
            f"Vinculados nesta sessão: {linked_count}\nAinda não vinculados: {remaining}",
        )

    def _build_imported_order_roll(self) -> None:
        if self._is_building_order:
            return
        self._is_building_order = True
        self.orders_dashboard.set_building_order(True, "PREPARANDO PEDIDO...")
        QApplication.processEvents()
        try:
            linked_orders = tuple(
                replace(
                    order,
                    items=[item for item in order.items if item.link_status == "linked" and item.linked_arts],
                )
                for order in self.order_import_state.imported_orders
                if any(item.link_status == "linked" and item.linked_arts for item in order.items)
            )
            build_dtf_print_plan(linked_orders, validate_files=False)
            self.pages.setCurrentWidget(self.production_review_page)
            self.production_review_page.review_orders(linked_orders)
            self._checkpoint_current_operation("production_review")
        except PrintPlanValidationError as error:
            QMessageBox.warning(self, "Montar pedido", str(error))
        except Exception:
            QMessageBox.warning(self, "Montar pedido", "Não foi possível iniciar a conferência do pedido.")
        finally:
            self._is_building_order = False
            self.orders_dashboard.set_building_order(False)
            self.orders_dashboard.refresh()

    def _apply_reviewed_plan(self, plan: DTFOrderPlan) -> None:
        result = self.production_review_page.validation_result
        if self._is_building_order:
            return
        if not result.is_valid:
            QMessageBox.warning(
                self, "Erros encontrados",
                f"Não foi possível montar o rolo porque existem {len(result.errors)} erro(s).\n\n"
                "Confira a caixa VERIFICAÇÕES antes de continuar.",
            )
            return
        self._is_building_order = True
        operation_id = str(uuid4())
        try:
            clear_existing = False
            if self.roll_view.has_artworks:
                warning = QMessageBox(self)
                warning.setIcon(QMessageBox.Icon.Warning)
                warning.setWindowTitle("Rolo com conteúdo")
                warning.setText("O rolo atual já possui artes.")
                warning.setInformativeText(
                    "Ao continuar, o rolo atual será limpo e as novas artes serão carregadas."
                )
                cancel = warning.addButton("CANCELAR", QMessageBox.ButtonRole.RejectRole)
                clear = warning.addButton(
                    "LIMPAR / MONTAR", QMessageBox.ButtonRole.DestructiveRole
                )
                warning.setDefaultButton(cancel)
                warning.exec()
                if warning.clickedButton() is not clear:
                    return
                clear_existing = True
            self.orders_dashboard.set_building_order(True, "CARREGANDO ARTES...")
            QApplication.processEvents()
            prepared = prepare_print_plan_for_roll(plan, self.artwork_panel.physical_size_cm)
            previous_entries = self.artwork_panel.artwork_entries() if clear_existing else ()
            try:
                if clear_existing:
                    self._clear_roll_project()
                for entry in prepared:
                    roll_key = self.artwork_panel.add_configured_artwork(
                        entry.file_path, entry.width_cm, entry.height_cm, entry.quantity,
                        entry.color_mode,
                    )
                    if self.roll_view.artwork_quantity(roll_key) != entry.quantity:
                        raise RuntimeError(f"Falha ao adicionar {entry.file_path.name}")
                self.orders_dashboard.set_building_order(True, "ORGANIZANDO ROLO DTF...")
                QApplication.processEvents()
                self.roll_view.regroup_artworks()
            except Exception:
                self._clear_roll_project()
                for path, width, height, quantity in previous_entries:
                    self.artwork_panel.add_configured_artwork(path, width, height, quantity)
                raise
            self.roll_canvas.show()
            self.pages.setCurrentWidget(self.editor_page)
            try:
                batch_number = self.production_history_repository.next_batch_number()
                settings = BatchRollSettingsSnapshot(
                    film_width_cm=self.settings.width_input.value(),
                    gap_cm=self.settings.gap_mm / 10,
                    dpi=int(self.settings.dpi_combo.currentText()),
                    automatic_division=self.settings.auto_split.isChecked(),
                    maximum_length_m=self.settings.length_input.value(),
                )
                batch = create_production_batch_snapshot(
                    self.production_review_page.reviewed_orders, plan, result, settings,
                    batch_number=batch_number, operation_id=operation_id,
                )
                saved = self.production_history_repository.save(batch)
                self.processed_order_repository.record(
                    self.production_review_page.reviewed_orders, saved.mounted_at or saved.created_at
                )
                self.statusBar().showMessage(
                    f"Rolo montado e lote {saved.batch_number} salvo no histórico.", 9000
                )
            except (ProductionHistoryStorageError, OSError, ValueError):
                QMessageBox.warning(
                    self, "Histórico de lotes",
                    "O rolo foi montado, mas não foi possível salvar o registro no histórico.",
                )
            if self.active_operation is not None:
                if not get_unlinked_items(self.order_import_state.all_items):
                    try:
                        self.active_operation_repository.clear_active()
                        self.active_operation = None
                        self._refresh_active_operation_card()
                    except ActiveOperationStorageError as error:
                        self.statusBar().showMessage(str(error), 15000)
                else:
                    self._checkpoint_current_operation("orders_dashboard")
        except PrintPlanValidationError as error:
            QMessageBox.warning(self, "Montar pedido", str(error))
        except (OSError, ValueError):
            QMessageBox.warning(
                self, "Montar pedido", "Não foi possível montar o rolo com as artes vinculadas."
            )
        except Exception:
            QMessageBox.warning(
                self, "Montar pedido", "Ocorreu um erro inesperado durante a montagem do rolo."
            )
        finally:
            self._is_building_order = False
            self.orders_dashboard.set_building_order(False)
            self.orders_dashboard.refresh()

    def _clear_roll_project(self) -> None:
        self.artwork_panel.clear_artworks()
        self.roll_view.clear_artworks()

    def _automatic_link_orders(self) -> None:
        if self._is_auto_linking or not self.order_import_state.all_items:
            return
        folder = self.settings.folder_path
        if not folder:
            QMessageBox.information(
                self, "Pasta das artes",
                "Selecione primeiro a Pasta das artes nas configurações do projeto.",
            )
            return
        self.order_import_state.last_art_folder = str(folder)
        self._checkpoint_current_operation("automatic_linking")
        self._is_auto_linking = True
        self.orders_dashboard.set_auto_linking(True)
        QApplication.processEvents()
        try:
            candidates = scan_art_directory(folder)
            outcome = auto_link_orders(
                self.order_import_state.imported_orders,
                candidates,
                self.link_memory_service,
                str(folder),
            )
            if not candidates and outcome.memory_linked_count == 0:
                QMessageBox.information(
                    self,
                    "Vinculação automática",
                    "Nenhuma arte compatível foi encontrada nesta pasta.",
                )
                return
            self.order_import_state.apply_auto_link(outcome.orders, outcome.results)
        except ArtDirectoryError as error:
            QMessageBox.warning(self, "Vinculação automática", str(error))
            return
        except OSError:
            QMessageBox.warning(
                self, "Vinculação automática", "Não foi possível acessar a pasta de artes."
            )
            return
        finally:
            self._is_auto_linking = False
            self.orders_dashboard.set_auto_linking(False)
            self._checkpoint_current_operation("orders_dashboard")
        AutomaticLinkSummaryDialog(outcome, self).exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            not getattr(self, "_authentication_logout", False)
            and hasattr(self, "manual_linking_page")
            and self.pages.currentWidget() is self.manual_linking_page
            and not self.manual_linking_page.confirm_can_leave()
        ):
            event.ignore()
            return
        super().closeEvent(event)

    def prepare_logout(self) -> bool:
        """Honor existing work guards before requesting remote revocation."""
        if self._export_timer.isActive():
            QMessageBox.information(self, "Sair da conta", "Aguarde a exportação terminar antes de sair da conta.")
            return False
        if self._is_importing_orders or self._is_auto_linking or self._is_building_order:
            QMessageBox.information(self, "Sair da conta", "Aguarde a operação atual terminar antes de sair da conta.")
            return False
        if (self.pages.currentWidget() is self.manual_linking_page
                and not self.manual_linking_page.confirm_can_leave()):
            return False
        self._authentication_logout = True
        return True

    def cancel_logout(self):
        self._authentication_logout = False


    def _update_roll_settings(self, artwork: ArtworkPanel, width_mm: float, gap_mm: float, cost: float) -> None:
        self.roll_view.set_roll_settings(width_mm, gap_mm)
        artwork.set_roll_settings(width_mm, cost)

    def _add_to_roll(self, file_path: str, width_mm: float, height_mm: float, quantity: int) -> None:
        self.roll_canvas.show()
        self.roll_view.add_artwork(file_path, width_mm, height_mm, quantity)

    def _remove_from_roll(self, file_path: Path) -> None:
        self.roll_view.remove_artwork(str(file_path))
        if not self.roll_view._artwork_items:
            self.roll_canvas.hide()

    def _set_artwork_folder(self, artwork: ArtworkPanel, folder: Path) -> None:
        artwork.artwork_folder = folder

    def _add_artwork(self, artwork: ArtworkPanel, folder: Path | None) -> None:
        initial_path = str(folder or Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar arte",
            initial_path,
            "Imagens (*.png *.jpg *.jpeg *.webp)",
        )
        if file_path:
            selected_path = Path(file_path)
            width_cm, height_cm = artwork.physical_size_cm(selected_path)
            dialog = ArtworkSetupDialog(selected_path, width_cm, height_cm, self)
            if dialog.exec() == dialog.DialogCode.Accepted:
                configured_width, configured_height, quantity = dialog.dimensions
                artwork.add_configured_artwork(
                    selected_path, configured_width, configured_height, quantity
                )

    def _import_orders(self) -> None:
        if self._is_importing_orders:
            return
        downloads_folder = Path.home() / "Downloads"
        initial_folder = downloads_folder if downloads_folder.is_dir() else Path.home()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar planilha da UpSeller",
            str(initial_folder),
            "Planilhas Excel (*.xlsx)",
        )
        if not file_path:
            return
        # Load the Excel reader only after the user chooses a spreadsheet. This
        # keeps startup fast and lets the file picker open immediately.
        from dtf_manager.services.order_import_service import (
            OrderImportError,
            import_upseller_orders,
        )

        if self.production_history_repository.load_warning:
            QMessageBox.warning(
                self, "Proteção contra duplicidade",
                "Não foi possível verificar se existem pedidos já processados. Corrija ou limpe o histórico antes de continuar.",
            )
            return
        self._is_importing_orders = True
        self.settings.set_importing(True)
        QApplication.processEvents()
        try:
            orders = import_upseller_orders(Path(file_path))
        except OrderImportError as error:
            QMessageBox.warning(self, "Importação de pedidos", str(error))
            return
        except Exception:
            QMessageBox.warning(self, "Importação de pedidos", "Ocorreu um erro inesperado ao ler a planilha.")
            return
        finally:
            self._is_importing_orders = False
            self.settings.set_importing(False)
        # Stock protection runs BEFORE processing: repeated spreadsheet, finalized orders.
        self._pending_stock_import = None
        decision = self.stock_controller.review_import(Path(file_path), orders)
        if decision is None or not decision.orders:
            self.statusBar().showMessage("Importação cancelada.", 6000)
            return
        orders = decision.orders
        self._pending_stock_import = decision
        analysis = analyze_imported_orders_against_history(
            orders, self.production_history_repository.list_all()
        )
        fingerprint = build_import_operation_fingerprint(orders)
        prepared_orders = [analyzed.order for analyzed in analysis.orders]
        active = self.active_operation
        if active is not None and active.import_fingerprint == fingerprint:
            dialog = ExistingOperationDialog(active, self)
            dialog.exec()
            if dialog.choice == ExistingOperationDialog.CONTINUE:
                self._continue_active_operation()
            elif dialog.choice == ExistingOperationDialog.RESTART:
                self.active_operation_repository.clear_active()
                self.active_operation = None
                self._activate_new_operation(orders, fingerprint, Path(file_path).name)
            else:
                self._pending_stock_import = None
                self.pages.setCurrentWidget(self.editor_page)
            return
        if active is not None:
            warning = QMessageBox(self)
            warning.setIcon(QMessageBox.Icon.Warning)
            warning.setWindowTitle("Operação em andamento")
            warning.setText("Existe outra operação em andamento.")
            warning.setInformativeText(
                f"Ela possui {active.metadata.order_count} pedidos e "
                f"{active.metadata.linked_count} itens vinculados.\n\n"
                "Substituir apagará somente o progresso dessa preparação."
            )
            replace_button = warning.addButton(
                "SUBSTITUIR OPERAÇÃO", QMessageBox.ButtonRole.DestructiveRole
            )
            warning.addButton("CANCELAR", QMessageBox.ButtonRole.RejectRole)
            warning.exec()
            if warning.clickedButton() is not replace_button:
                self._pending_stock_import = None
                self.pages.setCurrentWidget(self.editor_page)
                return
            self.active_operation_repository.clear_active()
            self.active_operation = None
        self._activate_new_operation(prepared_orders, fingerprint, Path(file_path).name)

    def _build_roll_area(self) -> QWidget:
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("DTF")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("panelTitle")
        zoom_out = QPushButton("-")
        zoom_out.setObjectName("iconButton")
        zoom_in = QPushButton("+")
        zoom_in.setObjectName("iconButton")
        fit = QPushButton("Ajustar a tela")
        fit.setObjectName("iconButton")
        header.addWidget(zoom_out)
        header.addWidget(self.zoom_label)
        header.addWidget(zoom_in)
        header.addWidget(fit)
        layout.addLayout(header)
        canvas = QFrame()
        self.roll_canvas = canvas
        canvas.setObjectName("rollCanvas")
        canvas_layout = QHBoxLayout(canvas)
        canvas_layout.setContentsMargins(4, 4, 4, 4)
        self.roll_view = RollView()
        canvas_layout.addWidget(self.roll_view, 1)
        layout.addWidget(canvas, 1)
        canvas.hide()
        layout.addStretch(1)   # keeps the footer at the very bottom while the canvas is hidden
        footer = QHBoxLayout()
        self.used_length_label = QLabel("Comprimento utilizado: 0,00 m")
        footer.addWidget(self.used_length_label)
        footer.addStretch()
        footer.addWidget(QLabel("Divisao: 1 de 1"))
        layout.addLayout(footer)
        zoom_out.clicked.connect(self._zoom_out)
        zoom_in.clicked.connect(self._zoom_in)
        fit.clicked.connect(self._fit_roll)
        return area

    def _update_used_length(self, used_meters: float) -> None:
        formatted = f"{used_meters:.2f}".replace(".", ",")
        self.used_length_label.setText(f"Comprimento utilizado: {formatted} m")

    def _update_zoom_label(self):
        self.zoom_label.setText(f"{self.roll_view.zoom_percent}%")

    def _zoom_in(self):
        self.roll_view.zoom_in()
        self._update_zoom_label()

    def _zoom_out(self):
        self.roll_view.zoom_out()
        self._update_zoom_label()

    def _fit_roll(self):
        self.roll_view.fit_roll()
        self._update_zoom_label()

    def _start_export(self) -> None:
        file_name, accepted = QInputDialog.getText(
            self,
            "Nome do arquivo",
            "Digite o nome do arquivo:",
            text="DTF_Manager_export",
        )
        if not accepted or not file_name.strip():
            return
        self._export_file_name = file_name.strip()
        self._export_stage = 1
        self._export_progress = 0
        self.settings.start_export()
        self._export_timer.start()

    def _advance_export(self) -> None:
        self._export_progress = min(100, self._export_progress + 5)
        stage_name = "Renderizando projeto" if self._export_stage == 1 else "Salvando projeto"
        self.settings.update_export_progress(self._export_progress, stage_name)
        if self._export_progress < 100:
            return
        if self._export_stage == 1:
            try:
                width_mm = self.settings.width_input.value() * 10
                max_length_m = (
                    self.settings.length_input.value()
                    if self.settings.auto_split.isChecked()
                    else None
                )
                self._output_paths = self.export_service.export_roll(
                    self.roll_view.scene(),
                    width_mm,
                    self.roll_view.sceneRect().height(),
                    300,
                    max_length_m,
                    self._export_file_name,
                )
            except (OSError, ValueError) as error:
                self._export_timer.stop()
                self.settings.fail_export(str(error))
                return
            self._export_stage = 2
            self._export_progress = 0
            self.settings.update_export_progress(0, "Salvando projeto")
            return
        self._export_timer.stop()
        self.settings.finish_export(self._output_paths)


def run_application() -> int:
    # Preserve the existing public entrypoint without duplicating bootstrap.
    from dtf_manager.core.bootstrap import run_application as bootstrap_application
    return bootstrap_application()
