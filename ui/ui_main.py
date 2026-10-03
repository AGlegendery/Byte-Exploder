# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main.ui'
##
## Created by: Qt User Interface Compiler version 6.10.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QProgressBar, QPushButton, QSizePolicy,
    QSpacerItem, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1100, 858)
        MainWindow.setLayoutDirection(Qt.RightToLeft)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.vl_root = QVBoxLayout(self.centralwidget)
        self.vl_root.setSpacing(10)
        self.vl_root.setObjectName(u"vl_root")
        self.vl_root.setContentsMargins(14, 14, 14, 14)
        self.hl_header = QHBoxLayout()
        self.hl_header.setObjectName(u"hl_header")
        self.lbl_title = QLabel(self.centralwidget)
        self.lbl_title.setObjectName(u"lbl_title")

        self.hl_header.addWidget(self.lbl_title)

        self.sp_header = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.hl_header.addItem(self.sp_header)

        self.btn_cancel = QPushButton(self.centralwidget)
        self.btn_cancel.setObjectName(u"btn_cancel")

        self.hl_header.addWidget(self.btn_cancel)


        self.vl_root.addLayout(self.hl_header)

        self.splitter_main = QSplitter(self.centralwidget)
        self.splitter_main.setObjectName(u"splitter_main")
        self.splitter_main.setOrientation(Qt.Vertical)
        self.w_top_tabs = QWidget(self.splitter_main)
        self.w_top_tabs.setObjectName(u"w_top_tabs")
        self.vl_tabs = QVBoxLayout(self.w_top_tabs)
        self.vl_tabs.setObjectName(u"vl_tabs")
        self.vl_tabs.setContentsMargins(0, 0, 0, 0)
        self.tabWidget = QTabWidget(self.w_top_tabs)
        self.tabWidget.setObjectName(u"tabWidget")
        self.tab_encrypt = QWidget()
        self.tab_encrypt.setObjectName(u"tab_encrypt")
        self.vl_encrypt = QVBoxLayout(self.tab_encrypt)
        self.vl_encrypt.setSpacing(12)
        self.vl_encrypt.setObjectName(u"vl_encrypt")
        self.gb_encrypt_file = QGroupBox(self.tab_encrypt)
        self.gb_encrypt_file.setObjectName(u"gb_encrypt_file")
        self.vl_encrypt_file = QVBoxLayout(self.gb_encrypt_file)
        self.vl_encrypt_file.setObjectName(u"vl_encrypt_file")
        self.hl_encrypt_file = QHBoxLayout()
        self.hl_encrypt_file.setObjectName(u"hl_encrypt_file")
        self.le_input_file = QLineEdit(self.gb_encrypt_file)
        self.le_input_file.setObjectName(u"le_input_file")

        self.hl_encrypt_file.addWidget(self.le_input_file)

        self.btn_browse_file = QPushButton(self.gb_encrypt_file)
        self.btn_browse_file.setObjectName(u"btn_browse_file")

        self.hl_encrypt_file.addWidget(self.btn_browse_file)


        self.vl_encrypt_file.addLayout(self.hl_encrypt_file)

        self.hl_block = QHBoxLayout()
        self.hl_block.setObjectName(u"hl_block")
        self.lbl_block = QLabel(self.gb_encrypt_file)
        self.lbl_block.setObjectName(u"lbl_block")

        self.hl_block.addWidget(self.lbl_block)

        self.cb_block_mode = QComboBox(self.gb_encrypt_file)
        self.cb_block_mode.addItem("")
        self.cb_block_mode.addItem("")
        self.cb_block_mode.setObjectName(u"cb_block_mode")

        self.hl_block.addWidget(self.cb_block_mode)

        self.sb_block_size = QSpinBox(self.gb_encrypt_file)
        self.sb_block_size.setObjectName(u"sb_block_size")
        self.sb_block_size.setEnabled(False)
        self.sb_block_size.setMinimum(8)
        self.sb_block_size.setMaximum(64)
        self.sb_block_size.setSingleStep(4)
        self.sb_block_size.setValue(16)

        self.hl_block.addWidget(self.sb_block_size)

        self.sp_block_right = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.hl_block.addItem(self.sp_block_right)


        self.vl_encrypt_file.addLayout(self.hl_block)

        self.btn_encrypt_file = QPushButton(self.gb_encrypt_file)
        self.btn_encrypt_file.setObjectName(u"btn_encrypt_file")

        self.vl_encrypt_file.addWidget(self.btn_encrypt_file)


        self.vl_encrypt.addWidget(self.gb_encrypt_file)

        self.sp_encrypt_bottom = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.vl_encrypt.addItem(self.sp_encrypt_bottom)

        self.tabWidget.addTab(self.tab_encrypt, "")
        self.tab_decrypt = QWidget()
        self.tab_decrypt.setObjectName(u"tab_decrypt")
        self.vl_decrypt = QVBoxLayout(self.tab_decrypt)
        self.vl_decrypt.setSpacing(12)
        self.vl_decrypt.setObjectName(u"vl_decrypt")
        self.gb_decrypt_image = QGroupBox(self.tab_decrypt)
        self.gb_decrypt_image.setObjectName(u"gb_decrypt_image")
        self.hl_decrypt_image = QHBoxLayout(self.gb_decrypt_image)
        self.hl_decrypt_image.setObjectName(u"hl_decrypt_image")
        self.le_image_file = QLineEdit(self.gb_decrypt_image)
        self.le_image_file.setObjectName(u"le_image_file")

        self.hl_decrypt_image.addWidget(self.le_image_file)

        self.btn_browse_image = QPushButton(self.gb_decrypt_image)
        self.btn_browse_image.setObjectName(u"btn_browse_image")

        self.hl_decrypt_image.addWidget(self.btn_browse_image)


        self.vl_decrypt.addWidget(self.gb_decrypt_image)

        self.gb_key = QGroupBox(self.tab_decrypt)
        self.gb_key.setObjectName(u"gb_key")
        self.vl_key = QVBoxLayout(self.gb_key)
        self.vl_key.setObjectName(u"vl_key")
        self.hl_key = QHBoxLayout()
        self.hl_key.setObjectName(u"hl_key")
        self.le_key = QLineEdit(self.gb_key)
        self.le_key.setObjectName(u"le_key")

        self.hl_key.addWidget(self.le_key)

        self.btn_load_key = QPushButton(self.gb_key)
        self.btn_load_key.setObjectName(u"btn_load_key")

        self.hl_key.addWidget(self.btn_load_key)

        self.btn_copy_key = QPushButton(self.gb_key)
        self.btn_copy_key.setObjectName(u"btn_copy_key")

        self.hl_key.addWidget(self.btn_copy_key)


        self.vl_key.addLayout(self.hl_key)

        self.hl_key_actions = QHBoxLayout()
        self.hl_key_actions.setObjectName(u"hl_key_actions")
        self.btn_check_key = QPushButton(self.gb_key)
        self.btn_check_key.setObjectName(u"btn_check_key")

        self.hl_key_actions.addWidget(self.btn_check_key)

        self.sp_key_actions = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.hl_key_actions.addItem(self.sp_key_actions)

        self.btn_decrypt_image = QPushButton(self.gb_key)
        self.btn_decrypt_image.setObjectName(u"btn_decrypt_image")

        self.hl_key_actions.addWidget(self.btn_decrypt_image)


        self.vl_key.addLayout(self.hl_key_actions)


        self.vl_decrypt.addWidget(self.gb_key)

        self.sp_decrypt_bottom = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.vl_decrypt.addItem(self.sp_decrypt_bottom)

        self.tabWidget.addTab(self.tab_decrypt, "")
        self.tab_preview = QWidget()
        self.tab_preview.setObjectName(u"tab_preview")
        self.vl_preview = QVBoxLayout(self.tab_preview)
        self.vl_preview.setSpacing(10)
        self.vl_preview.setObjectName(u"vl_preview")
        self.lbl_preview = QLabel(self.tab_preview)
        self.lbl_preview.setObjectName(u"lbl_preview")
        self.lbl_preview.setFrameShape(QFrame.StyledPanel)
        self.lbl_preview.setAlignment(Qt.AlignCenter)

        self.vl_preview.addWidget(self.lbl_preview)

        self.table_metadata = QTableWidget(self.tab_preview)
        if (self.table_metadata.columnCount() < 2):
            self.table_metadata.setColumnCount(2)
        __qtablewidgetitem = QTableWidgetItem()
        self.table_metadata.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.table_metadata.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        self.table_metadata.setObjectName(u"table_metadata")
        self.table_metadata.setRowCount(0)
        self.table_metadata.setColumnCount(2)

        self.vl_preview.addWidget(self.table_metadata)

        self.tabWidget.addTab(self.tab_preview, "")

        self.vl_tabs.addWidget(self.tabWidget)

        self.splitter_main.addWidget(self.w_top_tabs)
        self.w_bottom_logs = QWidget(self.splitter_main)
        self.w_bottom_logs.setObjectName(u"w_bottom_logs")
        self.vl_logs = QVBoxLayout(self.w_bottom_logs)
        self.vl_logs.setObjectName(u"vl_logs")
        self.vl_logs.setContentsMargins(0, 0, 0, 0)
        self.progressBar = QProgressBar(self.w_bottom_logs)
        self.progressBar.setObjectName(u"progressBar")
        self.progressBar.setValue(0)
        self.progressBar.setTextVisible(True)

        self.vl_logs.addWidget(self.progressBar)

        self.lbl_verbose = QLabel(self.w_bottom_logs)
        self.lbl_verbose.setObjectName(u"lbl_verbose")

        self.vl_logs.addWidget(self.lbl_verbose)

        self.te_verbose = QTextEdit(self.w_bottom_logs)
        self.te_verbose.setObjectName(u"te_verbose")

        self.vl_logs.addWidget(self.te_verbose)

        self.splitter_main.addWidget(self.w_bottom_logs)

        self.vl_root.addWidget(self.splitter_main)

        MainWindow.setCentralWidget(self.centralwidget)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"Byte Exploder", None))
        self.lbl_title.setStyleSheet(QCoreApplication.translate("MainWindow", u"font-size:18px;font-weight:700;", None))
        self.lbl_title.setText(QCoreApplication.translate("MainWindow", u"Byte Exploder Pro", None))
        self.btn_cancel.setText(QCoreApplication.translate("MainWindow", u"\u23f9\ufe0f \u0644\u063a\u0648 \u0639\u0645\u0644\u06cc\u0627\u062a", None))
        self.gb_encrypt_file.setTitle(QCoreApplication.translate("MainWindow", u"\u0627\u0646\u062a\u062e\u0627\u0628 \u0641\u0627\u06cc\u0644", None))
        self.le_input_file.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u0645\u0633\u06cc\u0631 \u0641\u0627\u06cc\u0644 \u0648\u0631\u0648\u062f\u06cc...", None))
        self.btn_browse_file.setText(QCoreApplication.translate("MainWindow", u"\u0645\u0631\u0648\u0631...", None))
        self.lbl_block.setText(QCoreApplication.translate("MainWindow", u"Block Size:", None))
        self.cb_block_mode.setItemText(0, QCoreApplication.translate("MainWindow", u"Auto", None))
        self.cb_block_mode.setItemText(1, QCoreApplication.translate("MainWindow", u"Manual", None))

        self.btn_encrypt_file.setText(QCoreApplication.translate("MainWindow", u"\U0001f680 \U00000634\U00000631\U00000648\U00000639 \U00000631\U00000645\U00000632\U000006af\U00000630\U00000627\U00000631\U000006cc", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_encrypt), QCoreApplication.translate("MainWindow", u"\U0001f512 \U00000631\U00000645\U00000632\U000006af\U00000630\U00000627\U00000631\U000006cc \U00000641\U00000627\U000006cc\U00000644", None))
        self.gb_decrypt_image.setTitle(QCoreApplication.translate("MainWindow", u"\u0627\u0646\u062a\u062e\u0627\u0628 \u0639\u06a9\u0633 \u0631\u0645\u0632\u0634\u062f\u0647", None))
        self.le_image_file.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u0645\u0633\u06cc\u0631 \u0639\u06a9\u0633 (PNG)...", None))
        self.btn_browse_image.setText(QCoreApplication.translate("MainWindow", u"\u0645\u0631\u0648\u0631...", None))
        self.gb_key.setTitle(QCoreApplication.translate("MainWindow", u"\u06a9\u0644\u06cc\u062f", None))
        self.le_key.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u0645\u0633\u06cc\u0631 \u0641\u0627\u06cc\u0644 \u06a9\u0644\u06cc\u062f (JSON)...", None))
        self.btn_load_key.setText(QCoreApplication.translate("MainWindow", u"\u0628\u0627\u0631\u06af\u0630\u0627\u0631\u06cc", None))
        self.btn_copy_key.setText(QCoreApplication.translate("MainWindow", u"\u06a9\u067e\u06cc", None))
        self.btn_check_key.setText(QCoreApplication.translate("MainWindow", u"\U0001f50d \U00000628\U00000631\U00000631\U00000633\U000006cc \U000006a9\U00000644\U000006cc\U0000062f", None))
        self.btn_decrypt_image.setText(QCoreApplication.translate("MainWindow", u"\U0001f680 \U00000634\U00000631\U00000648\U00000639 \U00000631\U00000645\U00000632\U000006af\U00000634\U00000627\U000006cc\U000006cc", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_decrypt), QCoreApplication.translate("MainWindow", u"\U0001f513 \U00000631\U00000645\U00000632\U000006af\U00000634\U00000627\U000006cc\U000006cc \U00000639\U000006a9\U00000633", None))
        self.lbl_preview.setText(QCoreApplication.translate("MainWindow", u"\u067e\u06cc\u0634\u200c\u0646\u0645\u0627\u06cc\u0634 \u0639\u06a9\u0633", None))
        ___qtablewidgetitem = self.table_metadata.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("MainWindow", u"\u0648\u06cc\u0698\u06af\u06cc", None));
        ___qtablewidgetitem1 = self.table_metadata.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("MainWindow", u"\u0645\u0642\u062f\u0627\u0631", None));
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_preview), QCoreApplication.translate("MainWindow", u"\U0001f441\U0000fe0f \U0000067e\U000006cc\U00000634\U0000200c\U00000646\U00000645\U00000627\U000006cc\U00000634", None))
        self.lbl_verbose.setText(QCoreApplication.translate("MainWindow", u"\u062e\u0631\u0648\u062c\u06cc \u0639\u0645\u0644\u06cc\u0627\u062a (Verbose):", None))
        self.te_verbose.setPlaceholderText(QCoreApplication.translate("MainWindow", u"Log...", None))
    # retranslateUi

