"""Lavender glass theme inspired by the user-provided dashboard reference.

Ambient peach and aqua light sits beneath translucent pearl surfaces.
Lavender is reserved for primary actions and selected states.
"""

from pathlib import Path


APP_STYLE = r"""
QWidget {
    color: #292630;
    font-family: "SF Pro Text", "PingFang SC", "Segoe UI", "Microsoft YaHei UI";
    font-size: 13px;
}
QMainWindow { background: #EEEBE9; }
QStackedWidget#PageStack, QWidget#PageSurface { background: transparent; }
QFrame#AppShell {
    background: qlineargradient(x1:0,y1:0,x2:0.7,y2:1,
        stop:0 rgba(255,255,255,230),stop:0.5 rgba(250,249,255,185),stop:1 rgba(245,246,255,90));
    border: 1px solid rgba(255,255,255,235); border-radius: 26px;
}
QFrame#Topbar { background: transparent; border: none; border-bottom: 1px solid rgba(218,209,231,100); }
QFrame#Navigation { background: rgba(234,230,242,125); border: 1px solid rgba(255,255,255,150); border-radius: 17px; }
QLabel#ProfileBadge { color: #756480; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #F3D9D0,stop:1 #D5C8EB); border: 2px solid #FFFFFF; border-radius: 16px; font-size: 11px; }
QLabel { background: transparent; }
QLabel#PageTitle { font-size: 25px; font-weight: 600; color: #292630; }
QLabel#PageSubtitle { color: #746B81; font-size: 12px; }
QLabel#SectionTitle { font-size: 16px; font-weight: 600; }
QLabel#MutedLabel, QLabel#SidebarCaption { color: #746B81; font-size: 12px; }
QLabel#SidebarCaption { padding: 8px 12px; font-size: 11px; }
QFrame#Sidebar { background: #F3EFF7; border: none; border-right: 1px solid #E9E3F0; }
QLabel#BrandMark { background: #987BD6; border-radius: 12px; min-width: 40px; min-height: 40px; }
QLabel#BrandText { font-size: 17px; font-weight: 600; }
QLabel#BrandSubtitle { color: #746B81; font-size: 10px; }
QFrame#WorkspaceCard { background: #ECECEF; border-radius: 10px; }
QLabel#WorkspaceTitle { color: #4B4555; font-size: 12px; font-weight: 600; }
QLabel#EnvironmentBadge { color: #746B81; font-size: 11px; padding: 5px 0; }
QPushButton {
    min-height: 18px; background: rgba(255,255,255,200); color: #4B4555;
    border: 1px solid rgba(255,255,255,225); border-radius: 11px; padding: 8px 13px;
}
QPushButton:hover { background: #F3EFF7; border-color: #CEBEDF; }
QPushButton:pressed { background: #E9EAED; }
QPushButton:focus { border: 1px solid #987BD6; }
QPushButton#PrimaryButton, QPushButton#AgentSendButton {
    color: #FFFFFF; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #B09ADE,stop:1 #9273D5); border: 1px solid #B7A3E1; font-weight: 600;
}
QPushButton#PrimaryButton:hover, QPushButton#AgentSendButton:hover { background: #8768C9; border-color: #8768C9; }
QPushButton#PrimaryButton:pressed, QPushButton#AgentSendButton:pressed { background: #7758B8; }
QPushButton#PrimaryButton:focus, QPushButton#AgentSendButton:focus { border: 2px solid #6547A2; padding: 6px 11px; }
QPushButton#SecondaryButton { color: #4B4555; }
QPushButton#DangerButton { color: #C93430; }
QPushButton#DangerButton:hover { background: #FFF1F0; border-color: #EAB9B5; }
QPushButton:disabled, QPushButton#PrimaryButton:disabled, QPushButton#SecondaryButton:disabled,
QPushButton#DangerButton:disabled, QPushButton#AgentSendButton:disabled {
    color: #949499; background: #F0F0F2; border-color: #E9E3F0;
}
QPushButton#NavButton {
    min-height: 22px; background: transparent; border: 1px solid transparent;
    border-radius: 12px; padding: 7px 18px; text-align: center; color: #746B81; font-size: 12px;
}
QPushButton#NavButton:hover { background: rgba(255,255,255,140); }
QPushButton#NavButton:checked { background: rgba(255,255,255,235); border-color: #FFFFFF; color: #39313F; font-weight: 600; }
QPushButton#NavButton:focus { border-color: #987BD6; }
QSplitter#ContentSplitter::handle:horizontal { background: transparent; width: 20px; }
QSplitter#ContentSplitter::handle:horizontal:hover { background: rgba(204,185,234,45); border-radius: 8px; }
QFrame#SummaryGroup { background: transparent; border: none; }
QFrame#SummaryCard { background: qlineargradient(x1:0,y1:0,x2:0.6,y2:1,stop:0 rgba(255,255,255,230),stop:1 rgba(248,245,255,120)); border: 1px solid rgba(255,255,255,240); border-radius: 17px; }
QFrame#SummaryCard:hover { background: rgba(255,255,255,235); border-color: #D6C5EE; }
QFrame#SummaryCard[active="true"] { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #FFFFFF,stop:1 #ECE3FA); border-color: #DDD0F2; }
QFrame#SummaryCard:focus { border-color: #987BD6; }
QLabel#CardLabel { color: #746B81; font-size: 12px; }
QLabel#CardValue { color: #292630; font-family: "SF Pro Display", "Segoe UI", "Microsoft YaHei UI"; font-size: 34px; font-weight: 500; }
QFrame#SummaryCard[active="true"] QLabel#CardValue { color: #8061BE; }
QFrame#SummaryCard[statusTone="offer"] QLabel#CardValue { color: #57866E; }
QLabel#CardUnit { color: #968DA2; font-size: 11px; padding-bottom: 5px; }
QFrame#TableSurface { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(255,255,255,165),stop:1 rgba(255,255,255,85)); border: 1px solid rgba(255,255,255,210); border-radius: 18px; }
QFrame#Toolbar { background: rgba(255,255,255,145); border: 1px solid rgba(255,255,255,215); border-radius: 16px; }
QFrame#TableToolbar { background: transparent; border: none; }
QLabel#SaveFeedback { color: #57866E; background: #ECF4EE; border-radius: 5px; padding: 4px 8px; font-size: 11px; }
QLineEdit, QPlainTextEdit, QComboBox {
    background: rgba(255,255,255,180); color: #292630; border: 1px solid rgba(218,207,232,150);
    border-radius: 7px; padding: 7px 10px;
    selection-background-color: #DFD2F4; selection-color: #292630;
}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover { border-color: #CEBEDF; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: #987BD6; }
QComboBox {
    combobox-popup: 0;
    min-height: 20px; color: #685778;
    background: qlineargradient(x1:0,y1:0,x2:0.8,y2:1,stop:0 rgba(255,255,255,240),stop:1 rgba(237,229,249,175));
    border: 1px solid rgba(255,255,255,240); border-radius: 10px; padding: 7px 10px;
}
QComboBox:hover { border-color: #D9CAEB; }
QComboBox:focus, QComboBox:on { border-color: #BFA5E1; }
QComboBox:disabled { color: #A69BB2; background: rgba(244,240,249,160); }
QComboBox::drop-down { width: 24px; border: none; background: transparent; }
QComboBox::down-arrow { image: url(__ASSETS__/chevron-down.svg); width: 11px; height: 11px; }
QComboBox::down-arrow:on { image: url(__ASSETS__/chevron-up.svg); }
QFrame#ComboPopupWindow { background: #F8F4FD; border: 1px solid #E1D5EF; border-radius: 13px; }
QListView#ComboPopup {
    color: #554B63;
    background: qlineargradient(x1:0,y1:0,x2:0.8,y2:1,stop:0 #FEFCFF,stop:1 #F2ECFA);
    border: none; border-radius: 12px; padding: 6px;
    outline: none; selection-background-color: transparent;
}
QListView#ComboPopup QScrollBar:vertical { width: 6px; margin: 8px 1px; }
QListView#ComboPopup QScrollBar::handle:vertical { background: #D5C6E8; border-radius: 2px; }
QTableWidget {
    background: transparent; alternate-background-color: rgba(255,255,255,38); color: #4B4555;
    border: none; gridline-color: #F0F0F2; outline: none;
    selection-background-color: #EEE7F9; selection-color: #292630;
}
QTableWidget::item { border: none; padding: 8px; }
QTableWidget::item:selected { background: #EEE7F9; color: #7555B1; }
QHeaderView::section {
    background: rgba(246,241,252,105); color: #746B81; border: none;
    border-top: 1px solid rgba(255,255,255,85); border-bottom: 1px solid rgba(228,217,242,70);
    padding: 10px 8px; font-size: 11px; font-weight: 600;
}
QTableCornerButton::section { background: transparent; border: none; }
QComboBox#TableEditor {
    min-height: 18px; color: #806A9F;
    border-radius: 10px; padding: 4px 6px 4px 10px; margin: 0 1px; font-size: 12px;
}
QComboBox#TableEditor:hover { border-color: #D9CAEB; }
QComboBox#TableEditor:focus, QComboBox#TableEditor:on { border-color: #BFA5E1; }
QComboBox#TableEditor[statusTone="offer"], QComboBox#StatusFilter[statusTone="offer"] { color: #608572; }
QComboBox#TableEditor[statusTone="pending"], QComboBox#StatusFilter[statusTone="pending"] { color: #8061BE; }
QComboBox#TableEditor[statusTone="ended"], QComboBox#StatusFilter[statusTone="ended"] { color: #8E8399; }
QPushButton#DateTimePickerButton {
    min-height: 24px; color: #655D71; background: transparent; border: 1px solid transparent;
    border-radius: 6px; padding: 5px 7px; margin: 0 3px; text-align: left; font-size: 12px;
}
QPushButton#DateTimePickerButton:hover, QPushButton#DateTimePickerButton:focus { background: #EEE7F9; border-color: #C2ACE6; color: #8061BE; }
QPushButton#DateTimePickerButton[empty="true"] { color: #968DA2; }
QFrame#AgentPanel { background: qlineargradient(x1:0,y1:0,x2:0.5,y2:1,stop:0 rgba(255,255,255,220),stop:0.5 rgba(238,230,251,105),stop:1 rgba(224,244,246,150)); border: 1px solid rgba(255,255,255,220); border-radius: 20px; }
QLabel#AgentTitle { font-size: 16px; font-weight: 600; }
QLabel#OnlineLabel { color: #57866E; font-size: 11px; padding: 4px 0; }
QLabel#ContextBadge { color: #7C6D92; background: rgba(237,229,247,140); border-radius: 9px; padding: 7px 11px; font-size: 11px; }
QLabel#AssistantMark { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #F5F0FF,stop:0.5 #E8DCFA,stop:1 #D5CCED); border: 1px solid rgba(255,255,255,240); border-radius: 20px; }
QLabel#WelcomeTitle { font-size: 21px; font-weight: 600; }
QLabel#WelcomeSubtitle { color: #746B81; font-size: 12px; }
QPushButton#SuggestionButton {
    color: #655D71; background: rgba(255,255,255,165); border: 1px solid rgba(255,255,255,240);
    border-radius: 12px; padding: 12px 13px; text-align: left; font-size: 12px;
}
QPushButton#SuggestionButton:hover { color: #8061BE; border-color: #CBB8EC; background: #F8F4FE; }
QPushButton#SuggestionButton:focus { border-color: #987BD6; }
QTextBrowser { background: #FFFFFF; border: 1px solid #E9E3F0; border-radius: 12px; padding: 14px; }
QTextBrowser#AgentMessages { background: transparent; border: none; padding: 0; color: #4B4555; }
QTextBrowser#AgentMessages QScrollBar:vertical { width: 5px; margin: 4px 0; }
QTextBrowser#AgentMessages QScrollBar::handle:vertical { min-height: 30px; background: #D8CEE5; border-radius: 2px; }
QTextBrowser#AgentMessages QScrollBar::handle:vertical:hover { background: #BDAECE; }
QFrame#Composer { background: rgba(255,255,255,195); border: 1px solid rgba(255,255,255,250); border-radius: 16px; }
QFrame#Composer[focused="true"] { border-color: #987BD6; }
QPlainTextEdit#AgentInput { background: transparent; border: none; border-radius: 0; padding: 2px; }
QLabel#InputHint { color: #746B81; font-size: 10px; }
QPushButton#AgentSendButton { min-width: 40px; border-radius: 7px; padding: 6px 12px; }
QFrame#EmailCandidateReview {
    background: rgba(255,255,255,210); border: 1px solid #DCCFED;
    border-radius: 14px;
}
QLabel#EmailCandidateTitle { color: #55476B; font-size: 13px; font-weight: 600; }
QLabel#EmailCandidateCount {
    color: #8061BE; background: #EEE7F9; border-radius: 7px;
    padding: 3px 7px; font-size: 10px;
}
QLabel#EmailCandidateHint, QLabel#EmailCandidateFeedback { color: #766C82; font-size: 10px; }
QTableWidget#EmailCandidateTable {
    background: transparent; border: 1px solid #E7DDF2; border-radius: 8px;
    alternate-background-color: #FAF8FD; font-size: 10px;
}
QTableWidget#EmailCandidateTable::item { padding: 5px; }
QTableWidget#EmailCandidateTable QHeaderView::section {
    background: #F3EEF9; color: #695B7A; border: none;
    border-bottom: 1px solid #E1D5EF; padding: 6px; font-size: 10px; font-weight: 600;
}
QFrame#Card, QFrame#InterviewSettings { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(255,255,255,230),stop:1 rgba(249,244,255,135)); border: 1px solid rgba(255,255,255,235); border-radius: 18px; }
QFrame#InterviewSettings { background: rgba(255,255,255,150); }
QFrame#JobSearchToolbar {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(255,255,255,210),stop:1 rgba(241,235,249,145));
    border: 1px solid rgba(255,255,255,235); border-radius: 15px;
}
QLabel#JobFilterLabel { color: #6F647A; font-size: 11px; font-weight: 600; }
QPushButton#CityPicker {
    color: #4E4359; background: rgba(255,255,255,205); border: 1px solid #DED3EA;
    border-radius: 9px; padding: 7px 30px 7px 11px; text-align: left;
}
QPushButton#CityPicker:hover, QPushButton#CityPicker:focus { color: #7555B1; border-color: #BDA8DD; background: #FBF9FE; }
QPushButton#CityPicker::menu-indicator {
    image: url(__ASSETS__/chevron-down.svg); subcontrol-origin: padding; subcontrol-position: center right;
    width: 11px; height: 11px; right: 10px;
}
QMenu#CityPickerMenu {
    color: #554B63; background: #FAF7FD; border: 1px solid #DED3EA;
    border-radius: 10px; padding: 7px;
}
QCheckBox#CityOption { color: #554B63; spacing: 9px; padding: 7px 9px; }
QCheckBox#CityOption:hover { color: #7555B1; background: #F1EAFB; border-radius: 7px; }
QCheckBox#CityOption::indicator { width: 15px; height: 15px; border: 1px solid #BFAFD1; border-radius: 4px; background: #FFFFFF; }
QCheckBox#CityOption::indicator:checked { background: #9273D5; border-color: #9273D5; }
QLabel#JobNotice { color: #6E637A; background: rgba(248,245,252,125); border-radius: 8px; padding: 7px 10px; font-size: 11px; }
QFrame#JobResultRow {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(255,255,255,235),stop:1 rgba(248,244,253,180));
    border: 1px solid rgba(222,211,234,205); border-radius: 14px;
}
QFrame#JobResultRow:hover { border-color: #CDBBE4; background: rgba(255,255,255,242); }
QLabel#JobSequence {
    color: #7253AE; background: #EEE7F8; border: 1px solid #DED0F0;
    border-radius: 11px; font-size: 15px; font-weight: 700;
}
QLabel#JobFieldLabel { color: #978CA2; font-size: 10px; padding-top: 2px; }
QLabel#JobPrimaryValue { color: #332D3A; font-size: 15px; font-weight: 600; }
QLabel#JobFieldValue { color: #5D5368; font-size: 12px; }
QLabel#JobSalary { color: #9B5D38; font-size: 13px; font-weight: 600; }
QFrame#JobActions {
    background: transparent; border: none; border-left: 1px solid rgba(222,211,234,175);
}
QLabel#JobLink { color: #7555B1; font-size: 12px; }
QLabel#JobLink a { color: #7555B1; text-decoration: none; }
QFrame#JdHoverArea { background: transparent; border: none; }
QLabel#JdTrigger { color: #7555B1; font-size: 12px; font-weight: 600; padding: 4px 0; }
QLabel#JdTrigger:hover { color: #604296; }
QFrame#JdPreview {
    background: #FCFAFE; border: 1px solid #CDBBE4; border-radius: 13px;
}
QLabel#JdBubbleTitle { color: #3C3447; font-size: 13px; font-weight: 600; }
QTextBrowser#JdText {
    color: #554B63; background: transparent; border: none; padding: 0;
    font-size: 12px; line-height: 1.45;
}
QLabel#JobEmptyState { color: #82778D; background: rgba(255,255,255,120); border: 1px dashed #D8CDE2; border-radius: 12px; padding: 36px; }
QPushButton#ResumeUploadButton {
    min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;
    padding: 0; background: rgba(255,255,255,115); border: 1px solid #DED5E8;
    border-radius: 9px;
}
QPushButton#ResumeUploadButton:hover { background: #F5F0FB; border-color: #BCA7D9; }
QPushButton#ResumeUploadButton:focus { background: #F5F0FB; border: 2px solid #987BD6; }
QPushButton#ResumeUploadButton:pressed { background: #EDE5F6; }
QPushButton#ResumeUploadButton:disabled { background: #F0F0F2; border-color: #E4DFE8; }
QLabel#ResumeFileName { color: #655D71; font-size: 11px; }
QLabel#ScoreBadge { color: #57866E; background: #ECF4EE; border-radius: 7px; padding: 6px 10px; font-size: 12px; font-weight: 600; }
QLabel#ReasonBox { color: #356046; background: #F2F7F3; border-radius: 8px; padding: 10px 12px; font-size: 12px; }
QLabel#RiskBox { color: #8A651C; background: #FCF7EB; border-radius: 8px; padding: 10px 12px; font-size: 12px; }
QLabel#JdBox { color: #655D71; background: #F3EFF7; border-radius: 8px; padding: 12px; }
QTextBrowser#InterviewTranscript { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(255,255,255,195),stop:1 rgba(236,225,250,80)); border: 1px solid rgba(255,255,255,210); border-radius: 18px; padding: 20px; }
QPlainTextEdit#InterviewAnswer { background: rgba(255,255,255,190); border-radius: 16px; padding: 12px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { min-height: 28px; background: #C8BED6; border-radius: 3px; }
QScrollBar::handle:horizontal { min-width: 28px; background: #C8BED6; border-radius: 3px; }
QScrollBar::handle:hover { background: #A193B6; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QFrame#DialogSurface, QFrame#DateTimePickerSurface { background: #FFFFFF; border: 1px solid #E5DFF0; border-radius: 16px; }
QFrame#DialogAccent { background: #E9E3F0; border: none; border-top-left-radius: 16px; border-top-right-radius: 16px; }
QLabel#DialogTitle { font-size: 19px; font-weight: 600; }
QLabel#DialogMessage { color: #4B4555; font-size: 14px; }
QLabel#DialogDetail { color: #746B81; font-size: 12px; }
QPushButton#DialogClose { min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; background: transparent; border: none; padding: 0; font-size: 20px; }
QPushButton#DialogClose:hover { background: #EEEEF0; }
QCalendarWidget#DateTimeCalendar { background: transparent; border: none; padding: 0 22px; }
QCalendarWidget#DateTimeCalendar QWidget#qt_calendar_navigationbar { background: #F3EFF7; border-radius: 8px; margin: 0 22px 8px 22px; }
QCalendarWidget#DateTimeCalendar QToolButton { color: #8061BE; background: transparent; border: none; border-radius: 6px; padding: 7px 10px; }
QCalendarWidget#DateTimeCalendar QToolButton:hover { background: #F0E9FA; }
QCalendarWidget#DateTimeCalendar QAbstractItemView { color: #4B4555; background: #FFFFFF; alternate-background-color: #FFFFFF; border: none; outline: none; selection-color: #FFFFFF; selection-background-color: #987BD6; }
QLabel#PickerFieldLabel { color: #4B4555; font-weight: 600; }
QComboBox#TimePartCombo { min-width: 90px; color: #8061BE; padding: 8px 10px 8px 12px; }
QToolTip { color: #4B4555; background: #FFFFFF; border: 1px solid #E5DFF0; padding: 6px; }
""".replace("__ASSETS__", (Path(__file__).resolve().parent / "assets").as_posix())
