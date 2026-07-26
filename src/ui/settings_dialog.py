"""设置对话框：配置税号 + 线程数（写入 config.ini）"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QSpinBox, QVBoxLayout,
)

from .. import config as _cfg
from ..config_manager import set_business_config
from .colors import Palette
from ..config import FONT_UI, FONT_MONO, SIZE_H2, SIZE_BODY, SIZE_SMALL


class SettingsDialog(QDialog):
    """业务配置对话框（税号 + 线程数）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(12)

        # 标题
        title = QLabel("业务配置")
        title.setFont(QFont(FONT_UI, SIZE_H2, QFont.Bold))
        title.setStyleSheet(f"color: {Palette.TEXT};")
        lay.addWidget(title)

        hint = QLabel("修改后点击「保存」即生效，下次处理使用新配置。")
        hint.setFont(QFont(FONT_UI, SIZE_SMALL))
        hint.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # 表单
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.tax_input = QLineEdit(_cfg.TARGET_TAX_ID)
        self.tax_input.setFont(QFont(FONT_MONO, SIZE_BODY))
        self.tax_input.setPlaceholderText("18 位统一社会信用代码")
        form.addRow("购买方税号", self.tax_input)

        self.workers_input = QSpinBox()
        self.workers_input.setRange(2, 16)
        self.workers_input.setValue(_cfg.MAX_WORKERS)
        self.workers_input.setFont(QFont(FONT_MONO, SIZE_BODY))
        self.workers_input.setSuffix(" 线程")
        form.addRow("并发线程数", self.workers_input)

        lay.addLayout(form)

        lay.addStretch()

        # 按钮区
        btn_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        lay.addWidget(btn_box)

    def _on_save(self):
        tax_id = self.tax_input.text().strip()
        if not re.fullmatch(r'[A-Z0-9]{18}', tax_id):
            QMessageBox.warning(
                self, "格式错误",
                "税号必须为 18 位大写字母+数字（统一社会信用代码格式）。",
            )
            return
        try:
            set_business_config(tax_id, self.workers_input.value())
        except OSError as e:
            QMessageBox.critical(self, "保存失败", f"无法写入配置文件: {e}")
            return
        # 实时更新内存中的配置常量
        _cfg.reload_business_config()
        self.accept()
