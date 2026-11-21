ROLL_OUTLINE_COLOR = "#4b1722"

APP_STYLE = """
QWidget { color: #ece8e9; font-family: "Segoe UI"; font-size: 13px; }
QMainWindow, #appRoot, #ordersDashboard, #manualLinkingPage, #linkMemoryPage, #productionReviewPage, #productionHistoryPage, #importAnalysisPage { background: #030304; }
QFrame#sidebar, QFrame#rightPanel { background: #070708; border: 1px solid #351018; border-radius: 10px; }
QLabel#eyebrow { color: #8f7f82; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QLabel#sectionTitle { color: #f7f2f3; font-size: 18px; font-weight: 700; }
QLabel#panelTitle { color: #eee8e9; font-size: 12px; font-weight: 700; }
QLabel#muted { color: #8f8587; font-size: 11px; }
QLabel#metricValue { color: #e73a59; font-size: 16px; font-weight: 700; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #0d0b0c; border: 1px solid #2b1a1d; border-radius: 6px;
    padding: 7px 10px; color: #f3edef; min-height: 22px;
    selection-background-color: #8f1730; selection-color: #ffffff;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #54202a; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { background: #100b0d; border: 1px solid #a8233e; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { color: #eee8e9; background: #0b090a; border: 1px solid #4a1620; selection-background-color: #641426; selection-color: #ffffff; outline: 0; }
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1a0c0f, stop:1 #0d090a);
    border: 1px solid #481521; border-radius: 6px; padding: 8px 12px; min-height: 20px; color: #eee8e9; font-weight: 600;
}
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #35101a, stop:1 #160b0e); border-color: #8f2038; color: #ffffff; }
QPushButton:pressed { background: #4a1020; border-color: #bd2949; }
QPushButton#primaryButton, QPushButton#addButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #210b10, stop:1 #410c18); border: 1px solid #6e1830; }
QPushButton#primaryButton:hover, QPushButton#addButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #35101a, stop:1 #641329); border-color: #b12645; }
QPushButton#exportButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5d1023, stop:0.45 #310b15, stop:1 #12080b); border: 1px solid #a32140; min-height: 22px; }
QPushButton#exportButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7c1730, stop:0.5 #470d1d, stop:1 #1b090e); border-color: #dc3154; }
QPushButton#regroupButton { background: #100b0d; border: 1px solid #6b1a2b; color: #e9dfe1; padding: 8px 12px; }
QPushButton#regroupButton:hover { background: #2c0d15; border-color: #b12645; color: #ffffff; }
QPushButton#iconButton { padding: 6px; min-width: 20px; min-height: 20px; font-size: 14px; }
QPushButton#removeButton { padding: 6px; min-height: 20px; font-size: 14px; color: #d72d4e; }
QPushButton#removeButton:hover { color: #ff5a75; border-color: #9c2039; }
QPushButton#previewColorButton { background: #170b0f; border: 1px solid #a52340; border-radius: 17px; padding: 0; min-width: 32px; min-height: 32px; font-size: 18px; }
QPushButton#previewColorButton:hover { background: #601328; border-color: #ef3e61; }
QFrame#selectedArtworkActions { background: #080708; border: 1px solid #8e2038; border-radius: 10px; }
QPushButton#artworkActionButton { background: #100b0d; border: 1px solid #41141d; border-radius: 7px; padding: 0; color: #f2e9eb; font-size: 16px; font-weight: 600; }
QPushButton#artworkActionButton:hover { background: #35101a; border-color: #b12746; color: #ffffff; }
QCheckBox { color: #b9afb1; spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; background: #0d0b0c; border: 1px solid #49202a; border-radius: 4px; }
QCheckBox::indicator:hover { border-color: #92213a; }
QCheckBox::indicator:checked { background: #b31f3e; border-color: #dc3154; }
QScrollArea { border: 0; background: transparent; }
QScrollArea QWidget#qt_scrollarea_viewport, QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical, QScrollBar:horizontal { background: #070708; margin: 2px; }
QScrollBar:vertical { width: 8px; }
QScrollBar:horizontal { height: 8px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #501522; min-height: 30px; min-width: 30px; border-radius: 4px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #8f2038; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QFrame#artCard { background: #0b090a; border: 1px solid #341219; border-radius: 8px; }
QFrame#artCard:hover { background: #0f0a0c; border-color: #741a2d; }
QFrame#artCard[selected="true"] { background: #180b10; border: 1px solid #bd2949; }
QFrame#artCard QSpinBox, QFrame#artCard QDoubleSpinBox { padding: 4px 3px; min-height: 20px; }
QLabel#artworkThumb { background: #170b0f; color: #d62d4d; border: 1px solid #41141e; border-radius: 6px; font-weight: 700; }
QLabel#artworkName { color: #f4edef; font-weight: 700; }
QFrame#summary { background: #090809; border: 1px solid #3c121b; border-radius: 8px; }
QFrame#activeOperationCard { background: #10090b; border: 1px solid #7a1d32; border-radius: 8px; }
QFrame#orderMetricCard { background: #090809; border: 1px solid #3c121b; border-radius: 8px; }
QFrame#productionStatusCard { background: #090809; border: 1px solid #3c121b; border-radius: 8px; }
QFrame#productionStatusCard[status="ready"] { border-color: #245d40; background: #07110c; }
QFrame#productionStatusCard[status="warning"] { border-color: #7b5222; background: #130e07; }
QFrame#productionStatusCard[status="error"] { border-color: #7b2032; background: #16080c; }
QLabel#productionStatus { font-size: 15px; font-weight: 700; }
QTreeWidget#productionIssues, QTreeWidget#productionContent { background: #070708; alternate-background-color: #0b090a; border: 1px solid #351018; border-radius: 8px; outline: 0; }
QTableWidget#historyTable { background: #070708; alternate-background-color: #0b090a; border: 1px solid #351018; border-radius: 8px; outline: 0; }
QTreeWidget#productionIssues::item, QTreeWidget#productionContent::item { padding: 7px; border-bottom: 1px solid #251014; }
QPushButton[selected="true"] { background: #4a1020; border-color: #bd2949; }
QLabel#linkedMetricValue { color: #54c98a; font-size: 16px; font-weight: 700; }
QLabel#unlinkedMetricValue { color: #e69b45; font-size: 16px; font-weight: 700; }
QLabel#emptyState { color: #8f8587; font-size: 14px; qproperty-alignment: AlignCenter; }
QLabel#productImagePlaceholder { background: #100b0d; color: #776a6d; border: 1px solid #35141b; border-radius: 6px; font-size: 10px; }
QTableWidget#orderItemsTable { background: #070708; alternate-background-color: #0b090a; border: 1px solid #351018; border-radius: 8px; outline: 0; }
QTableWidget#linkMemoryTable { background: #070708; alternate-background-color: #0b090a; border: 1px solid #351018; border-radius: 8px; outline: 0; }
QTableWidget#orderItemsTable::item { padding: 8px; border-bottom: 1px solid #251014; }
QHeaderView::section { background: #100b0d; color: #9d9093; border: 0; border-bottom: 1px solid #4a1720; padding: 8px; font-size: 10px; font-weight: 700; }
QFrame#widthCard { background: #10090b; border: 1px solid #591827; border-radius: 8px; }
QFrame#rollCanvas { background: #080808; border: 1px solid #3a121a; border-radius: 8px; }
QGraphicsView#rollView { background: #080808; border: 0; }
QDialog { background: #080708; }
QDialog#artworkSetupDialog { background: #070607; }
QDialog#orderImportSummaryDialog { background: #070607; }
QDialog#automaticLinkSummaryDialog { background: #070607; }
QDialog#printPlanConfirmationDialog { background: #070607; }
QListWidget#printPlanList { background: #0b090a; border: 1px solid #35141b; border-radius: 7px; padding: 5px; }
QFrame#manualColumn { background: #070708; border: 1px solid #351018; border-radius: 10px; }
QFrame#manualArtCard { background: #0b090a; border: 1px solid #3c141c; border-radius: 8px; }
QLabel#manualProductImage { background: #0b090a; color: #776a6d; border: 1px solid #35141b; border-radius: 8px; }
QLabel#manualArtPreview { background: #171415; color: #776a6d; border: 1px solid #45202a; border-radius: 6px; font-size: 10px; }
QToolButton#artSuggestion { background: #101012; border: 1px solid #2d2226; border-radius: 8px; color: #e8dfe1; padding: 4px; }
QToolButton#artSuggestion:hover { background: #241018; border-color: #8f2038; }
QLabel#dialogTitle { color: #f6eff1; font-size: 18px; font-weight: 700; }
QFrame#previewCard, QFrame#setupFormCard { background: #0c090a; border: 1px solid #3b141c; border-radius: 9px; }
QLabel#artworkPreview { background: #030304; border: 1px solid #451620; border-radius: 7px; }
QLabel#dialogFileName { color: #d6cdcf; font-size: 11px; font-weight: 600; }
QLabel#fieldLabel { color: #a79b9e; font-size: 11px; font-weight: 600; }
QLabel#unitLabel { color: #8c7e81; font-size: 11px; }
QLabel#infoIcon { color: #d63655; background: #170b0f; border: 1px solid #5a1827; border-radius: 9px; font-size: 11px; font-weight: 700; }
QLabel#infoIcon:hover { color: #ff607a; background: #2a0d15; border-color: #a52340; }
QMenuBar { background: transparent; }
QLabel#greetingLabel { color: #eee8e9; font-size: 12px; font-weight: 600; }
QLabel#licenseLabel { color: #a79b9e; font-size: 11px; }
QLabel#licenseLabel[tone="trial"], QLabel#licenseLabel[tone="warning"] { color: #e69b45; font-weight: 700; }
QLabel#licenseLabel[tone="offline"] { color: #e73a59; font-weight: 700; }
QMenu { background: #0b090a; color: #eee8e9; border: 1px solid #4a1620; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: #641426; color: #ffffff; }
QToolTip { color: #eee8e9; background: #100b0d; border: 1px solid #6e1b2e; border-radius: 6px; padding: 6px 9px; font-size: 11px; }
QDialog#artworkSetupDialog QSpinBox, QDialog#artworkSetupDialog QDoubleSpinBox { background: #0d0a0b; padding: 5px 8px; min-height: 18px; }
QDialogButtonBox QPushButton { min-width: 96px; padding: 8px 13px; }
QDialogButtonBox QPushButton#primaryButton { min-width: 132px; }
QProgressBar { color: #e9dfe1; background: #0a0809; border: 1px solid #3d141c; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #72162d, stop:1 #d52c4d); border-radius: 4px; }
QTabWidget#mainTabs::pane { border: 0; background: #030304; }
QTabWidget#mainTabs > QTabBar::tab { background: transparent; color: #8f8587; padding: 9px 22px; border: 0; border-bottom: 2px solid transparent; font-weight: 700; }
QTabWidget#mainTabs > QTabBar::tab:selected { color: #f7f2f3; border-bottom: 2px solid #d52c4d; }
QTabWidget#mainTabs > QTabBar::tab:hover:!selected { color: #e9dfe1; }
QWidget#stockTab { background: #030304; }
QPushButton#stockViewButton { padding: 6px 16px; }
QPushButton#stockViewButton:checked { background: #4a1020; border-color: #bd2949; color: #ffffff; }
QPushButton#finalizeButton { background: #100b0d; border: 1px solid #6b1a2b; color: #e9dfe1; min-height: 22px; }
QPushButton#finalizeButton:hover { background: #2c0d15; border-color: #b12645; color: #ffffff; }
QPushButton#finalizeButton:disabled { color: #5d5356; border-color: #2a1318; background: #0a0809; }
QTableWidget#stockTable, QTableWidget#futureTable, QTableWidget#balanceTable, QTableWidget#separationTable, QTableWidget#pendingTable, QTableWidget#validationTable, QTableWidget#finalizeTable, QTableWidget#movementsTable, QTableWidget#importsTable, QTableWidget#aliasesTable { background: #070708; alternate-background-color: #0b090a; border: 1px solid #351018; border-radius: 8px; outline: 0; }
QTableWidget#stockTable::item, QTableWidget#futureTable::item, QTableWidget#balanceTable::item { font-size: 15px; font-weight: 700; }
QLabel#pendingWarning, QLabel#importWarning { color: #e69b45; font-weight: 700; }
QTabBar::tab { background: #100b0d; color: #a79b9e; padding: 7px 16px; border: 1px solid #351018; }
QTabBar::tab:selected { color: #ffffff; background: #2c0d15; }
QFrame#summaryCard { background: #0b090a; border: 1px solid #3d141c; border-radius: 10px; }
QLabel#summaryTitle { color: #a79b9e; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#summaryValue { color: #f7f2f3; font-size: 26px; font-weight: 700; }
QLabel#summaryValue[tone="alert"] { color: #ff5a75; }
QLabel#stockHint { color: #e4dadc; font-size: 13px; font-weight: 600; }
QLabel#quickBanner { color: #ffffff; background: #4a1020; border: 1px solid #bd2949; border-radius: 6px; padding: 8px 12px; font-size: 13px; font-weight: 700; }
QPushButton#quickCountButton { border-color: #8f2038; }
QPushButton#quickCountButton:checked { background: #4a1020; border-color: #ef3e61; color: #ffffff; }
QTableWidget#stockTable QLineEdit { background: #1a0e13; color: #ffffff; border: 2px solid #ef3e61; font-size: 15px; font-weight: 700; padding: 0 4px; }
"""
