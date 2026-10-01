"""PySide6 客户端共用的视觉主题。

配色参考 HTML 原型，同时保留桌面客户端现有的信息布局。
"""

APP_STYLE = r"""
QMainWindow {
    background: #F1F1F6;
}
QWidget {
    color: #25232D;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 14px;
}
QWidget#AppRoot, QStackedWidget#PageStack, QWidget#PageSurface {
    background: #FFFFFF;
}
QLabel {
    background: transparent;
}
QLabel#PageTitle {
    color: #25232D;
    font-size: 27px;
    font-weight: 800;
}
QLabel#PageSubtitle {
    color: #8C8898;
    font-size: 13px;
}
QLabel#SectionTitle {
    color: #25232D;
    font-size: 17px;
    font-weight: 750;
}
QLabel#MutedLabel {
    color: #8C8898;
    font-size: 12px;
}

QFrame#Sidebar {
    background: #FFFFFF;
    border: none;
    border-right: 1px solid #EBE9F2;
}
QLabel#BrandMark {
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    color: #FFFFFF;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #A873FA, stop:1 #7137D2);
    border-radius: 12px;
    font-size: 18px;
    font-weight: 800;
}
QLabel#BrandText {
    color: #25232D;
    font-size: 19px;
    font-weight: 800;
}
QLabel#EnvironmentBadge {
    color: #8C8898;
    background: #FAF9FD;
    border: 1px solid #EBE9F2;
    border-radius: 10px;
    padding: 9px 11px;
    font-size: 11px;
}

QFrame#AgentPanel {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #F8F7FA, stop:0.72 #F5F4F7, stop:1 #F8F3F3);
    border: none;
    border-left: 1px solid #E5E3E8;
}
QSplitter#ContentSplitter::handle:horizontal {
    background: #EBE9F2;
    width: 5px;
}
QSplitter#ContentSplitter::handle:horizontal:hover,
QSplitter#ContentSplitter::handle:horizontal:pressed {
    background: #CFC0F4;
}
QLabel#AgentTitle {
    color: #242228;
    font-size: 18px;
    font-weight: 800;
}
QLabel#OnlineLabel {
    color: #218B68;
    background: #E7F5EF;
    border: 1px solid #CDE9DD;
    border-radius: 9px;
    padding: 4px 8px;
    font-size: 11px;
}
QLabel#InputHint {
    color: #A09CA5;
    font-size: 10px;
}
QLabel#SaveFeedback {
    color: #238B63;
    background: #E6F8EF;
    border-radius: 8px;
    padding: 5px 9px;
    font-size: 11px;
    font-weight: 700;
}

QPushButton {
    min-height: 18px;
    color: #6F687B;
    background: #FFFFFF;
    border: 1px solid #EBE9F2;
    border-radius: 10px;
    padding: 8px 13px;
}
QPushButton:hover {
    color: #8652E8;
    background: #F8F4FF;
    border-color: #CFC0F4;
}
QPushButton:pressed {
    background: #F0E8FF;
}
QPushButton#PrimaryButton {
    color: #FFFFFF;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #9161ED, stop:1 #7746D5);
    border: 1px solid #8652E8;
    font-weight: 700;
}
QPushButton#PrimaryButton:hover {
    color: #FFFFFF;
    background: #6E37D1;
    border-color: #6E37D1;
}
QPushButton#SecondaryButton {
    color: #6F42C9;
    background: #FFFFFF;
    border: 1px solid #DFD4F7;
}
QPushButton#NavButton {
    min-height: 24px;
    color: #817B91;
    background: transparent;
    border: none;
    border-radius: 12px;
    padding: 11px 13px;
    text-align: left;
    font-weight: 600;
}
QPushButton#NavButton:hover {
    color: #8652E8;
    background: #F8F4FF;
}
QPushButton#NavButton:checked {
    color: #8652E8;
    background: #F3EDFF;
    font-weight: 750;
}

QFrame#SummaryCard, QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #EBE9F2;
    border-radius: 14px;
}
QFrame#SummaryCard:hover {
    background: #FCFAFF;
    border: 1px solid #D9CEF8;
}
QFrame#SummaryCard[active="true"] {
    background: #FCFAFF;
    border: 1px solid #CFC0F4;
}
QFrame#SummaryCard[statusTone="offer"] QLabel#CardValue {
    color: #238B63;
}
QFrame#SummaryCard[statusTone="offer"]:hover,
QFrame#SummaryCard[statusTone="offer"][active="true"] {
    background: #F2FBF7;
    border: 1px solid #91D6BA;
}
QLabel#CardLabel {
    color: #8C8898;
    font-size: 12px;
}
QLabel#CardValue {
    color: #25232D;
    font-size: 28px;
    font-weight: 800;
}
QLabel#ScoreBadge {
    color: #7547D2;
    background: #F3EDFF;
    border-radius: 9px;
    padding: 5px 9px;
    font-size: 12px;
    font-weight: 700;
}
QLabel#ReasonBox {
    color: #6F42C9;
    background: #F3EDFF;
    border-radius: 9px;
    padding: 9px 11px;
}
QLabel#RiskBox {
    color: #B27621;
    background: #FFF3DD;
    border-radius: 9px;
    padding: 9px 11px;
}
QLabel#JdBox {
    color: #6F687B;
    background: #FCFBFF;
    border: 1px solid #EBE9F2;
    border-radius: 10px;
    padding: 12px;
}

QFrame#Toolbar {
    background: #FAF9FD;
    border: 1px solid #EBE9F2;
    border-radius: 12px;
}
QLineEdit, QPlainTextEdit, QComboBox, QDateTimeEdit {
    color: #25232D;
    background: #FAF9FD;
    border: 1px solid #EBE9F2;
    border-radius: 9px;
    padding: 8px 10px;
    selection-background-color: #E9DEFC;
}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QDateTimeEdit:hover {
    border-color: #D9CEF8;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateTimeEdit:focus {
    background: #FFFFFF;
    border-color: #CFC0F4;
}
QLineEdit::placeholder, QPlainTextEdit::placeholder {
    color: #AAA5B2;
}
QComboBox::drop-down {
    width: 30px;
    border: none;
    border-left: 1px solid #E6DFF3;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}
QDateTimeEdit::drop-down {
    width: 25px;
    border: none;
}
QTableWidget QComboBox#TableEditor {
    color: #6237AE;
    background: #F7F3FF;
    border: 1px solid #E2D8F8;
    border-radius: 9px;
    padding: 5px 30px 5px 10px;
    font-weight: 700;
}
QTableWidget QDateTimeEdit#TableEditor {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px 6px;
}
QTableWidget QComboBox#TableEditor:hover,
QTableWidget QDateTimeEdit#TableEditor:hover,
QTableWidget QComboBox#TableEditor:focus,
QTableWidget QDateTimeEdit#TableEditor:focus {
    background: #F3EDFF;
    border: 1px solid #D9CEF8;
}
QComboBox#TableEditor[statusTone="offer"],
QComboBox#StatusFilter[statusTone="offer"] {
    color: #238B63;
    background: #E6F8EF;
    border: 1px solid #BEE8D5;
    font-weight: 700;
}
QComboBox#TableEditor[statusTone="applied"],
QComboBox#StatusFilter[statusTone="applied"] {
    color: #41699B;
    background: #EAF2FB;
    border: 1px solid #C8DAEE;
    font-weight: 700;
}
QComboBox#TableEditor[statusTone="pending"],
QComboBox#StatusFilter[statusTone="pending"] {
    color: #9A6500;
    background: #FFF5D9;
    border: 1px solid #F0D48A;
    font-weight: 700;
}
QComboBox#TableEditor[statusTone="ended"],
QComboBox#StatusFilter[statusTone="ended"] {
    color: #777382;
    background: #F0EEF3;
    border: 1px solid #DDD9E3;
    font-weight: 700;
}
QComboBox QAbstractItemView {
    color: #25232D;
    background: #FFFFFF;
    border: 1px solid #D9CEF8;
    selection-color: #6E37D1;
    selection-background-color: #F3EDFF;
    outline: none;
    padding: 5px;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 5px 10px;
    border-radius: 6px;
}

QTableWidget {
    color: #4F495B;
    background: #FFFFFF;
    alternate-background-color: #FCFBFE;
    border: 1px solid #EBE9F2;
    border-radius: 13px;
    gridline-color: #F1EFF5;
    selection-color: #25232D;
    selection-background-color: #F3EDFF;
    outline: none;
}
QTableWidget::item {
    padding: 8px;
    border: none;
}
QTableWidget::item:selected {
    color: #5F3E9C;
    background: #F3EDFF;
}
QHeaderView::section {
    color: #817B91;
    background: #FAF9FD;
    border: none;
    border-bottom: 1px solid #EBE9F2;
    padding: 11px 9px;
    font-weight: 700;
}
QTableCornerButton::section {
    background: #FAF9FD;
    border: none;
}

QTextBrowser {
    color: #5F596B;
    background: #FBFAFF;
    border: 1px solid #EBE9F2;
    border-radius: 13px;
    padding: 10px;
}
QTextBrowser#AgentMessages {
    color: #514D57;
    background: rgba(255, 255, 255, 220);
    border: 1px solid #E5E3E8;
    border-radius: 16px;
    padding: 13px;
}
QPlainTextEdit#AgentInput {
    color: #2F2C33;
    background: rgba(255, 255, 255, 235);
    border: 1px solid #DDD9E1;
    border-radius: 15px;
    padding: 11px 13px;
    selection-background-color: #DDD1F6;
}
QPlainTextEdit#AgentInput:hover {
    border-color: #CBC4D3;
}
QPlainTextEdit#AgentInput:focus {
    background: #FFFFFF;
    border: 1px solid #BDADE0;
}
QPushButton#AgentSendButton {
    min-width: 62px;
    color: #FFFFFF;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #8D63D7, stop:1 #6F45BC);
    border: 1px solid #7950C5;
    border-radius: 12px;
    padding: 8px 14px;
    font-weight: 700;
}
QPushButton#AgentSendButton:hover {
    color: #FFFFFF;
    background: #6940B4;
    border-color: #6940B4;
}
QPushButton#AgentSendButton:disabled {
    color: #91899D;
    background: #E8E4EC;
    border-color: #DDD8E2;
}
QScrollArea, QScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    width: 8px;
    margin: 3px;
    background: transparent;
}
QScrollBar::handle:vertical {
    min-height: 28px;
    background: #DCD7E7;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #C9BCE8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    height: 0px;
    background: transparent;
}
QMessageBox {
    background: #FFFFFF;
}
"""
