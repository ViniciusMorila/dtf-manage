# ---- Theme: wine + gold (dark). Every color of the application style lives here. -------------
THEME = {
    "BG": "#08060a",              # window, empty areas, inputs
    "PANEL": "#110c10",           # panels, cards, lists, menus, dialogs
    "ELEV": "#191217",            # elevated surface: secondary buttons, inactive tabs, headers
    "BORDER": "#33232b",          # default border
    "TEXT": "#f4eef0",            # main text
    "MUTED": "#a89aa1",           # secondary text / captions
    "DISABLED": "#6f6268",        # muted text for disabled controls (QSS has no opacity)
    "WINE": "#8b1a2f",            # primary: buttons, active tab, focus, checked, selection
    "WINE_HOVER": "#a3223a",      # primary, hover
    "WINE_PRESSED": "#6e1425",    # primary, pressed
    "ON_WINE": "#ffffff",         # text over wine
    "WINE_LIGHT": "#e8788a",      # highlight text / hover over dark
    "WINE_SOFT": "#2e0f18",       # soft wine background: badges, highlights, selection
    "ROLL_BG": "#170f14",         # roll film
    "HEADER_LEFT": "#0d080b",     # header gradient (left)
    "GOLD": "#e6c48a",            # gold accent
    "GOLD_LINE": "rgba(230, 196, 138, 84)",   # gold at 33%
    "NAME": "#d2405a",            # customer name
    "ALT_ROW": "#14100f",         # alternate table row
    # semantic colors (kept from the previous theme)
    "ERROR": "#ff5a75", "ERROR_STRONG": "#e73a59", "ERROR_BUTTON": "#d72d4e",
    "AMBER": "#e69b45", "GREEN": "#54c98a",
    "OK_BG": "#07110c", "OK_BORDER": "#245d40",
    "WARN_BG": "#130e07", "WARN_BORDER": "#7b5222",
    "ERR_BG": "#16080c", "ERR_BORDER": "#7b2032",
}

ROLL_OUTLINE_COLOR = THEME["BORDER"]

_APP_STYLE_TEMPLATE = """
QWidget { color: @TEXT@; font-family: "Segoe UI"; font-size: 13px; }
QMainWindow, #appRoot, #ordersDashboard, #manualLinkingPage, #linkMemoryPage, #productionReviewPage, #productionHistoryPage, #importAnalysisPage { background: @BG@; }
QFrame#sidebar, QFrame#rightPanel { background: @PANEL@; border: 1px solid @BORDER@; border-radius: 10px; }
QLabel#eyebrow { color: @MUTED@; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QLabel#sectionTitle { color: @TEXT@; font-size: 18px; font-weight: 700; }
QLabel#panelTitle { color: @TEXT@; font-size: 12px; font-weight: 700; }
QLabel#muted { color: @MUTED@; font-size: 11px; }
QLabel#metricValue { color: @GOLD@; font-size: 16px; font-weight: 700; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: @BG@; border: 1px solid @BORDER@; border-radius: 6px;
    padding: 7px 10px; color: @TEXT@; min-height: 22px;
    selection-background-color: @WINE@; selection-color: @ON_WINE@;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: @WINE@; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { background: @BG@; border: 1px solid @WINE@; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { color: @TEXT@; background: @PANEL@; border: 1px solid @BORDER@; selection-background-color: @WINE@; selection-color: @ON_WINE@; outline: 0; }
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 @ELEV@, stop:1 @ELEV@);
    border: 1px solid @BORDER@; border-radius: 6px; padding: 8px 12px; min-height: 20px; color: @TEXT@; font-weight: 600;
}
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 @ELEV@, stop:1 @ELEV@); border-color: @WINE@; color: @TEXT@; }
QPushButton:pressed { background: @WINE_SOFT@; border-color: @WINE@; }
QPushButton:disabled { color: @DISABLED@; border-color: @BORDER@; }
QPushButton#primaryButton, QPushButton#addButton { background: @WINE@; border: 1px solid @WINE@; color: @ON_WINE@; }
QPushButton#primaryButton:hover, QPushButton#addButton:hover { background: @WINE_HOVER@; border-color: @WINE_HOVER@; }
QPushButton#primaryButton:pressed, QPushButton#addButton:pressed { background: @WINE_PRESSED@; border-color: @WINE_PRESSED@; }
QPushButton#primaryButton:disabled, QPushButton#addButton:disabled { background: @WINE_SOFT@; border-color: @BORDER@; color: @DISABLED@; }
QPushButton#exportButton { background: @WINE@; border: 1px solid @WINE@; color: @ON_WINE@; min-height: 22px; }
QPushButton#exportButton:hover { background: @WINE_HOVER@; border-color: @WINE_HOVER@; }
QPushButton#exportButton:pressed { background: @WINE_PRESSED@; border-color: @WINE_PRESSED@; }
QPushButton#exportButton:disabled { background: @WINE_SOFT@; border-color: @BORDER@; color: @DISABLED@; }
QPushButton#regroupButton { background: @ELEV@; border: 1px solid @BORDER@; color: @TEXT@; padding: 8px 12px; }
QPushButton#regroupButton:hover { background: @ELEV@; border-color: @WINE@; color: @TEXT@; }
QPushButton#iconButton { padding: 6px; min-width: 20px; min-height: 20px; font-size: 14px; }
QPushButton[pill="true"] { border-radius: 15px; padding: 6px 14px; min-height: 22px; }
QPushButton#removeButton { padding: 6px; min-height: 20px; font-size: 14px; color: @ERROR_BUTTON@; }
QPushButton#removeButton:hover { color: @ERROR@; border-color: @WINE@; }
QPushButton#previewColorButton { background: @ELEV@; border: 1px solid @WINE@; border-radius: 17px; padding: 0; min-width: 32px; min-height: 32px; font-size: 18px; }
QPushButton#previewColorButton:hover { background: @WINE_SOFT@; border-color: @WINE_LIGHT@; }
QFrame#selectedArtworkActions { background: @PANEL@; border: 1px solid @WINE@; border-radius: 10px; }
QPushButton#artworkActionButton { background: @ELEV@; border: 1px solid @BORDER@; border-radius: 7px; padding: 0; color: @TEXT@; font-size: 16px; font-weight: 600; }
QPushButton#artworkActionButton:hover { background: @WINE_SOFT@; border-color: @WINE@; color: @TEXT@; }
QCheckBox { color: @TEXT@; spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; background: @BG@; border: 1px solid @BORDER@; border-radius: 4px; }
QCheckBox::indicator:hover { border-color: @WINE@; }
QCheckBox::indicator:checked { background: @WINE@; border-color: @WINE@; }
QScrollArea { border: 0; background: transparent; }
QScrollArea QWidget#qt_scrollarea_viewport, QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical, QScrollBar:horizontal { background: @PANEL@; margin: 2px; }
QScrollBar:vertical { width: 8px; }
QScrollBar:horizontal { height: 8px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: @BORDER@; min-height: 30px; min-width: 30px; border-radius: 4px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: @WINE@; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QFrame#artCard { background: @PANEL@; border: 1px solid @BORDER@; border-radius: 8px; }
QFrame#artCard:hover { background: @PANEL@; border-color: @WINE@; }
QFrame#artCard[selected="true"] { background: @WINE_SOFT@; border: 1px solid @WINE@; }
QFrame#artCard QSpinBox, QFrame#artCard QDoubleSpinBox { padding: 4px 3px; min-height: 20px; }
QLabel#artworkThumb { background: @ELEV@; color: @WINE_LIGHT@; border: 1px solid @BORDER@; border-radius: 6px; font-weight: 700; }
QLabel#artworkName { color: @TEXT@; font-weight: 700; }
QFrame#summary { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @WINE_SOFT@, stop:1 @ELEV@); border: 1px solid @WINE@; border-top: 1px solid @GOLD@; border-radius: 8px; }
QFrame#activeOperationCard { background: @PANEL@; border: 1px solid @WINE@; border-radius: 8px; }
QFrame#orderMetricCard { background: @PANEL@; border: 1px solid @BORDER@; border-radius: 8px; }
QFrame#productionStatusCard { background: @PANEL@; border: 1px solid @BORDER@; border-radius: 8px; }
QFrame#productionStatusCard[status="ready"] { border-color: @OK_BORDER@; background: @OK_BG@; }
QFrame#productionStatusCard[status="warning"] { border-color: @WARN_BORDER@; background: @WARN_BG@; }
QFrame#productionStatusCard[status="error"] { border-color: @ERR_BORDER@; background: @ERR_BG@; }
QLabel#productionStatus { font-size: 15px; font-weight: 700; }
QTreeWidget#productionIssues, QTreeWidget#productionContent { background: @PANEL@; alternate-background-color: @ALT_ROW@; border: 1px solid @BORDER@; border-radius: 8px; outline: 0; }
QTableWidget#historyTable { background: @PANEL@; alternate-background-color: @ALT_ROW@; border: 1px solid @BORDER@; border-radius: 8px; outline: 0; }
QTreeWidget#productionIssues::item, QTreeWidget#productionContent::item { padding: 7px; border-bottom: 1px solid @BORDER@; }
QTreeWidget::item:selected, QTableWidget::item:selected { background: @WINE_SOFT@; color: @WINE_LIGHT@; }
QTableWidget { gridline-color: @BORDER@; }
QPushButton[selected="true"] { background: @WINE@; border-color: @WINE@; color: @ON_WINE@; }
QLabel#linkedMetricValue { color: @GREEN@; font-size: 16px; font-weight: 700; }
QLabel#unlinkedMetricValue { color: @AMBER@; font-size: 16px; font-weight: 700; }
QLabel#emptyState { color: @MUTED@; font-size: 14px; qproperty-alignment: AlignCenter; }
QLabel#productImagePlaceholder { background: @ELEV@; color: @MUTED@; border: 1px solid @BORDER@; border-radius: 6px; font-size: 10px; }
QTableWidget#orderItemsTable { background: @PANEL@; alternate-background-color: @ALT_ROW@; border: 1px solid @BORDER@; border-radius: 8px; outline: 0; }
QTableWidget#linkMemoryTable { background: @PANEL@; alternate-background-color: @ALT_ROW@; border: 1px solid @BORDER@; border-radius: 8px; outline: 0; }
QTableWidget#orderItemsTable::item { padding: 8px; border-bottom: 1px solid @BORDER@; }
QHeaderView::section { background: @ELEV@; color: @MUTED@; border: 0; border-bottom: 1px solid @BORDER@; padding: 8px; font-size: 10px; font-weight: 700; }
QFrame#widthCard { background: @PANEL@; border: 1px solid @WINE@; border-radius: 8px; }
QFrame#rollCanvas { background: @BG@; border: 1px solid @WINE@; border-radius: 8px; }
QGraphicsView#rollView { background: @BG@; border: 0; }
QDialog { background: @PANEL@; }
QMessageBox { background: @PANEL@; }
QMessageBox QPushButton:default { background: @WINE@; border-color: @WINE@; color: @ON_WINE@; }
QDialog#artworkSetupDialog { background: @BG@; }
QDialog#orderImportSummaryDialog { background: @BG@; }
QDialog#automaticLinkSummaryDialog { background: @BG@; }
QDialog#printPlanConfirmationDialog { background: @BG@; }
QListWidget#printPlanList { background: @PANEL@; border: 1px solid @BORDER@; border-radius: 7px; padding: 5px; }
QFrame#manualColumn { background: @PANEL@; border: 1px solid @BORDER@; border-radius: 10px; }
QFrame#manualArtCard { background: @PANEL@; border: 1px solid @BORDER@; border-radius: 8px; }
QLabel#manualProductImage { background: @ELEV@; color: @MUTED@; border: 1px solid @BORDER@; border-radius: 8px; }
QLabel#manualArtPreview { background: @ELEV@; color: @MUTED@; border: 1px solid @BORDER@; border-radius: 6px; font-size: 10px; }
QToolButton#artSuggestion { background: @ELEV@; border: 1px solid @BORDER@; border-radius: 8px; color: @TEXT@; padding: 4px; }
QToolButton#artSuggestion:hover { background: @WINE_SOFT@; border-color: @WINE@; }
QLabel#dialogTitle { color: @TEXT@; font-size: 18px; font-weight: 700; }
QFrame#previewCard, QFrame#setupFormCard { background: @PANEL@; border: 1px solid @BORDER@; border-radius: 9px; }
QLabel#artworkPreview { background: @BG@; border: 1px solid @BORDER@; border-radius: 7px; }
QLabel#dialogFileName { color: @TEXT@; font-size: 11px; font-weight: 600; }
QLabel#fieldLabel { color: @MUTED@; font-size: 11px; font-weight: 600; }
QLabel#unitLabel { color: @MUTED@; font-size: 11px; }
QLabel#infoIcon { color: @WINE_LIGHT@; background: @WINE_SOFT@; border: 1px solid @WINE@; border-radius: 9px; font-size: 11px; font-weight: 700; }
QLabel#infoIcon:hover { color: @ON_WINE@; background: @WINE@; border-color: @WINE_LIGHT@; }
QMenuBar { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @HEADER_LEFT@, stop:1 @WINE_SOFT@); border-bottom: 1px solid @BORDER@; }
QLabel#greetingLabel { color: @NAME@; font-size: 12px; font-weight: 700; }
QLabel#licenseLabel { color: @GOLD@; background: @WINE_SOFT@; border: 1px solid @GOLD_LINE@; font-size: 11px; }
QLabel#licenseLabel[tone="trial"], QLabel#licenseLabel[tone="warning"] { color: @AMBER@; font-weight: 700; }
QLabel#licenseLabel[tone="offline"] { color: @ERROR_STRONG@; font-weight: 700; }
QMenu { background: @PANEL@; color: @TEXT@; border: 1px solid @BORDER@; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: @WINE@; color: @ON_WINE@; }
QToolTip { color: @TEXT@; background: @PANEL@; border: 1px solid @BORDER@; border-radius: 6px; padding: 6px 9px; font-size: 11px; }
QDialog#artworkSetupDialog QSpinBox, QDialog#artworkSetupDialog QDoubleSpinBox { background: @BG@; padding: 5px 8px; min-height: 18px; }
QDialogButtonBox QPushButton { min-width: 96px; padding: 8px 13px; }
QDialogButtonBox QPushButton#primaryButton { min-width: 132px; }
QProgressBar { color: @TEXT@; background: @BG@; border: 1px solid @BORDER@; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @WINE@, stop:1 @WINE_LIGHT@); border-radius: 4px; }
QTabWidget#mainTabs::tab-bar { alignment: center; }
QTabWidget#mainTabs::pane { border: 0; background: @BG@; }
QTabWidget#mainTabs > QTabBar::tab { background: @ELEV@; color: @TEXT@; padding: 9px 22px; border: 0; border-bottom: 2px solid @BORDER@; font-weight: 700; }
QTabWidget#mainTabs > QTabBar::tab:selected { background: @WINE@; color: @ON_WINE@; border-bottom: 2px solid @WINE@; }
QTabWidget#mainTabs > QTabBar::tab:hover:!selected { color: @TEXT@; border-bottom: 2px solid @WINE@; }
QWidget#stockTab { background: @BG@; }
QPushButton#stockViewButton { padding: 6px 16px; }
QPushButton#stockViewButton:checked { background: @WINE@; border-color: @WINE@; color: @ON_WINE@; }
QPushButton#finalizeButton { background: transparent; border: 1px solid @WINE@; color: @WINE_LIGHT@; min-height: 22px; }
QPushButton#finalizeButton:hover { background: @WINE_SOFT@; border-color: @WINE@; color: @WINE_LIGHT@; }
QPushButton#finalizeButton:disabled { color: @DISABLED@; border-color: @BORDER@; background: transparent; }
QTableWidget#stockTable, QTableWidget#futureTable, QTableWidget#balanceTable, QTableWidget#separationTable, QTableWidget#pendingTable, QTableWidget#validationTable, QTableWidget#finalizeTable, QTableWidget#movementsTable, QTableWidget#importsTable, QTableWidget#aliasesTable { background: @PANEL@; alternate-background-color: @ALT_ROW@; border: 1px solid @BORDER@; border-radius: 8px; outline: 0; }
QTableWidget#stockTable::item, QTableWidget#futureTable::item, QTableWidget#balanceTable::item { font-size: 15px; font-weight: 700; }
QLabel#pendingWarning, QLabel#importWarning { color: @AMBER@; font-weight: 700; }
QTabBar::tab { background: @ELEV@; color: @TEXT@; padding: 7px 16px; border: 1px solid @BORDER@; }
QTabBar::tab:selected { color: @ON_WINE@; background: @WINE@; }
QTabBar::tab:hover:!selected { border-color: @WINE@; }
QTableWidget#stockTable { background: @BG@; border: 0; }
QTableWidget#artStockTable, QTableWidget#artSeparationTable, QTableWidget#finalizeArtTable, QTableWidget#artMatchesTable { background: @PANEL@; alternate-background-color: @ALT_ROW@; border: 1px solid @BORDER@; border-radius: 8px; outline: 0; }
QTableWidget#artStockTable::item, QTableWidget#artSeparationTable::item { font-size: 14px; }
QTableWidget#artStockTable QLineEdit { background: @ELEV@; color: @TEXT@; border: 2px solid @WINE_LIGHT@; font-size: 15px; font-weight: 700; padding: 0 4px; }
QFrame#summaryCard { background: @PANEL@; border: 1px solid @BORDER@; border-radius: 10px; }
QLabel#summaryTitle { color: @MUTED@; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#summaryValue { color: @GOLD@; font-size: 26px; font-weight: 700; }
QLabel#summaryValue[tone="alert"] { color: @ERROR@; }
QLabel#stockHint { color: @TEXT@; font-size: 13px; font-weight: 600; }
QLabel#quickBanner { color: @WINE_LIGHT@; background: @WINE_SOFT@; border: 1px solid @WINE@; border-radius: 6px; padding: 8px 12px; font-size: 13px; font-weight: 700; }
QPushButton#quickCountButton { border-color: @WINE@; }
QPushButton#quickCountButton:checked { background: @WINE@; border-color: @WINE_LIGHT@; color: @ON_WINE@; }
QTableWidget#stockTable QLineEdit { background: @ELEV@; color: @TEXT@; border: 2px solid @WINE_LIGHT@; font-size: 15px; font-weight: 700; padding: 0 4px; }
"""


def _themed(template: str) -> str:
    for name, value in THEME.items():
        template = template.replace(f"@{name}@", value)
    assert "@" not in template.replace("@media", ""), "unresolved theme token"
    return template


APP_STYLE = _themed(_APP_STYLE_TEMPLATE)
