"""设置对话框：业务配置 + 邮箱自动拉取 + AI 审核（写入 config.ini）

整个表单包在 QScrollArea 中，小屏幕（低分辨率）下可滚动，不会溢出界面。
"""
import re

import imaplib
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .. import config as _cfg
from ..config import FONT_UI, FONT_MONO, SIZE_H2, SIZE_BODY, SIZE_SMALL, SIZE_TINY
from ..config_manager import (
    get_ai_api_base, get_ai_api_key, get_ai_config, get_ai_enabled, get_ai_model,
    get_email_auth_code, get_email_config, get_email_days_back,
    get_email_poll_minutes, get_email_username, get_inbox_dir,
    set_ai_config, set_business_config, set_email_config,
)
from .colors import Palette
from .components import AccentBar
from .styles import QSS


class SettingsDialog(QDialog):
    """设置对话框（业务配置 + 邮箱拉取 + AI 审核）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumSize(680, 680)
        self.resize(760, 820)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(14)

        # ── 顶部装饰条（与主页面签名元素一致：朱砂→琥珀→青 渐变）──
        self.accent_bar = AccentBar()
        self.accent_bar.set_progress(1.0)
        lay.addWidget(self.accent_bar)

        header = QFrame()
        header.setObjectName("SettingsHeader")
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(18, 16, 18, 16)
        header_lay.setSpacing(14)
        header_copy = QVBoxLayout()
        header_copy.setSpacing(3)
        eyebrow = QLabel("WORKSPACE CONFIGURATION")
        eyebrow.setObjectName("SettingsEyebrow")
        title = QLabel("设置中心")
        title.setObjectName("SettingsTitle")
        subtitle = QLabel("管理发票识别、邮箱收件箱与智能审核服务")
        subtitle.setObjectName("SettingsSubtitle")
        header_copy.addWidget(eyebrow)
        header_copy.addWidget(title)
        header_copy.addWidget(subtitle)
        header_lay.addLayout(header_copy, stretch=1)
        badge = QLabel("本地配置")
        badge.setObjectName("SettingsBadge")
        header_lay.addWidget(badge, alignment=Qt.AlignTop)
        lay.addWidget(header)

        # 与主窗口共用同一套「墨韵」样式表，保证风格统一
        self.setStyleSheet(QSS)

        # ── 滚动区（容纳全部表单，小屏可滚动）──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        c_lay = QVBoxLayout(container)
        c_lay.setContentsMargins(4, 2, 4, 4)
        c_lay.setSpacing(12)

        # ══════════ 业务配置 ══════════
        c_lay.addWidget(self._section_title("01  /  业务配置"))
        c_lay.addWidget(self._section_hint("修改后点击「保存」即生效，下次处理使用新配置。"))

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

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

        c_lay.addLayout(form)

        # ══════════ 邮箱自动拉取 ══════════
        c_lay.addWidget(self._section_divider())
        c_lay.addWidget(self._section_title("02  /  邮箱自动拉取"))

        email = get_email_config()
        self.email_enabled = QCheckBox("启用邮箱自动拉取")
        self.email_enabled.setObjectName("FeatureToggle")
        self.email_enabled.setChecked(email['enabled'].lower() in ('1', 'true', 'yes', 'on'))
        c_lay.addWidget(self.email_enabled)

        form2 = QFormLayout()
        form2.setSpacing(10)
        form2.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.imap_host_input = QLineEdit(email['imap_host'] or 'imap.qq.com')
        self.imap_host_input.setFont(QFont(FONT_MONO, SIZE_BODY))
        form2.addRow("IMAP 服务器", self.imap_host_input)

        self.imap_port_input = QSpinBox()
        self.imap_port_input.setRange(1, 65535)
        try:
            self.imap_port_input.setValue(int(email['imap_port']))
        except (ValueError, TypeError):
            self.imap_port_input.setValue(993)
        form2.addRow("端口", self.imap_port_input)

        self.email_user_input = QLineEdit(get_email_username())
        self.email_user_input.setFont(QFont(FONT_MONO, SIZE_BODY))
        self.email_user_input.setPlaceholderText("发票转发到此邮箱")
        form2.addRow("邮箱账号", self.email_user_input)

        self.email_auth_input = QLineEdit(get_email_auth_code())
        self.email_auth_input.setFont(QFont(FONT_MONO, SIZE_BODY))
        self.email_auth_input.setEchoMode(QLineEdit.Password)
        self.email_auth_input.setPlaceholderText("IMAP 授权码（非登录密码）")
        auth_row = QHBoxLayout()
        auth_row.setSpacing(8)
        auth_row.addWidget(self.email_auth_input, stretch=1)
        self.test_btn = QPushButton("测试连接")
        self.test_btn.setCursor(Qt.PointingHandCursor)
        self.test_btn.clicked.connect(self._test_connection)
        auth_row.addWidget(self.test_btn)
        form2.addRow("IMAP 授权码", auth_row)

        self.inbox_dir_input = QLineEdit(email['inbox_dir'] or '发票收件箱')
        self.inbox_dir_input.setFont(QFont(FONT_MONO, SIZE_BODY))
        self.inbox_dir_input.setPlaceholderText("相对程序目录或绝对路径")
        form2.addRow("收件箱目录", self.inbox_dir_input)

        self.days_back_input = QSpinBox()
        self.days_back_input.setRange(1, 365)
        self.days_back_input.setValue(get_email_days_back())
        self.days_back_input.setSuffix(" 天")
        form2.addRow("拉取最近", self.days_back_input)

        self.poll_minutes_input = QSpinBox()
        self.poll_minutes_input.setRange(0, 1440)
        self.poll_minutes_input.setValue(get_email_poll_minutes())
        self.poll_minutes_input.setSuffix(" 分钟")
        self.poll_minutes_input.setSpecialValueText("0 = 关闭（仅手动）")
        form2.addRow("自动轮询", self.poll_minutes_input)

        c_lay.addLayout(form2)

        c_lay.addWidget(self._section_hint(
            "授权码获取：QQ 邮箱网页版 → 设置 → 账户 → 开启「IMAP/SMTP 服务」→ 生成授权码。"
            "授权码经 Windows DPAPI 加密后保存（config.ini 中为 dpapi: 密文，不保留明文）。"
        ))

        # ══════════ AI 审核 ══════════
        c_lay.addWidget(self._section_divider())
        c_lay.addWidget(self._section_title("03  /  AI 审核"))

        ai = get_ai_config()
        self.ai_enabled = QCheckBox("启用 AI 审核")
        self.ai_enabled.setObjectName("FeatureToggle")
        self.ai_enabled.setChecked(ai['enabled'].lower() in ('1', 'true', 'yes', 'on'))
        c_lay.addWidget(self.ai_enabled)

        form3 = QFormLayout()
        form3.setSpacing(10)
        form3.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.ai_key_input = QLineEdit(get_ai_api_key())
        self.ai_key_input.setFont(QFont(FONT_MONO, SIZE_BODY))
        self.ai_key_input.setEchoMode(QLineEdit.Password)
        self.ai_key_input.setPlaceholderText("sk- 开头的 DeepSeek API Key")
        form3.addRow("API Key", self.ai_key_input)

        self.ai_base_input = QLineEdit(get_ai_api_base())
        self.ai_base_input.setFont(QFont(FONT_MONO, SIZE_BODY))
        form3.addRow("接口地址", self.ai_base_input)

        self.ai_model_input = QLineEdit(get_ai_model())
        self.ai_model_input.setFont(QFont(FONT_MONO, SIZE_BODY))
        self.ai_model_input.setPlaceholderText("deepseek-v4-flash")
        form3.addRow("模型", self.ai_model_input)

        c_lay.addLayout(form3)

        c_lay.addWidget(self._section_hint(
            "API Key 获取：https://platform.deepseek.com 申请（sk- 开头）。"
            "API Key 经 Windows DPAPI 加密后保存，不保留明文。"
            "审核结果只作提示，不会阻断处理流程。"
        ))

        c_lay.addStretch()
        scroll.setWidget(container)
        lay.addWidget(scroll, stretch=1)

        # ── 按钮区 ──
        btn_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        lay.addWidget(btn_box)

        # ── 统一控件外观（复用主页面 objectName 规则）──
        # 所有文本输入框套用 #PathEntry（暖纸底 + 暖色边框 + 朱砂聚焦）
        for _le in (
            self.tax_input, self.imap_host_input, self.email_user_input,
            self.email_auth_input, self.inbox_dir_input,
            self.ai_key_input, self.ai_base_input, self.ai_model_input,
        ):
            _le.setObjectName("PathEntry")

        # 「测试连接」= 次要描边按钮
        self.test_btn.setObjectName("OutlineBtn")

        # 底部按钮盒：保存=朱砂实心，取消=次要描边
        save_btn = btn_box.button(QDialogButtonBox.Save)
        cancel_btn = btn_box.button(QDialogButtonBox.Cancel)
        if save_btn is not None:
            save_btn.setObjectName("PrimaryBtn")
            save_btn.style().unpolish(save_btn)
            save_btn.style().polish(save_btn)
        if cancel_btn is not None:
            cancel_btn.setObjectName("OutlineBtn")
            cancel_btn.style().unpolish(cancel_btn)
            cancel_btn.style().polish(cancel_btn)

    # ── 通用构造 ──────────────────────────────────────
    @staticmethod
    def _section_title(text: str) -> QLabel:
        frame = QFrame()
        frame.setObjectName("SettingsSectionHeader")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 8, 0, 2)
        row.setSpacing(10)
        marker = QFrame()
        marker.setObjectName("SettingsSectionMarker")
        marker.setFixedSize(4, 24)
        row.addWidget(marker)
        label = QLabel(text)
        label.setObjectName("SettingsSectionTitle")
        label.setFont(QFont(FONT_UI, SIZE_H2, QFont.Bold))
        row.addWidget(label)
        row.addStretch()
        return frame

    @staticmethod
    def _section_hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont(FONT_UI, SIZE_TINY))
        label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _section_divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {Palette.DIVIDER};")
        return line

    # ── 测试 IMAP 连接 ────────────────────────────────
    def _test_connection(self):
        """用当前填写的账号/授权码测试 IMAP 登录（同步，最多等 10 秒）"""
        host = self.imap_host_input.text().strip() or 'imap.qq.com'
        port = self.imap_port_input.value()
        username = self.email_user_input.text().strip()
        auth_code = self.email_auth_input.text().strip()
        if not username or not auth_code:
            QMessageBox.warning(self, "配置不完整", "请先填写邮箱账号和 IMAP 授权码。")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(host, port, timeout=10)
            mail.login(username, auth_code)
            QMessageBox.information(self, "连接成功", "IMAP 登录成功，配置可用。")
        except Exception as e:
            QMessageBox.critical(
                self, "连接失败",
                f"无法连接邮箱：\n{e}\n\n请检查账号、授权码、服务器地址与端口。",
            )
        finally:
            if mail is not None:
                try:
                    mail.logout()
                except Exception:
                    pass
            QApplication.restoreOverrideCursor()

    # ── 保存 ──────────────────────────────────────────
    def _on_save(self):
        tax_id = self.tax_input.text().strip()
        if not re.fullmatch(r'[A-Z0-9]{18}', tax_id):
            QMessageBox.warning(
                self, "格式错误",
                "税号必须为 18 位大写字母+数字（统一社会信用代码格式）。",
            )
            return

        # 邮箱校验
        email_enabled = self.email_enabled.isChecked()
        username = self.email_user_input.text().strip()
        auth_code = self.email_auth_input.text().strip()
        if email_enabled and (not username or not auth_code):
            QMessageBox.warning(
                self, "配置不完整",
                "启用邮箱拉取需要填写邮箱账号和 IMAP 授权码。",
            )
            return

        # AI 校验
        ai_enabled = self.ai_enabled.isChecked()
        ai_key = self.ai_key_input.text().strip()
        if ai_enabled and not ai_key:
            QMessageBox.warning(
                self, "配置不完整",
                "启用 AI 审核需要填写 DeepSeek API Key。",
            )
            return

        try:
            set_business_config(tax_id, self.workers_input.value())
            set_email_config(
                enabled='true' if email_enabled else 'false',
                imap_host=self.imap_host_input.text().strip() or 'imap.qq.com',
                imap_port=str(self.imap_port_input.value()),
                username=username,
                auth_code=auth_code,
                inbox_dir=self.inbox_dir_input.text().strip() or '发票收件箱',
                days_back=str(self.days_back_input.value()),
                poll_minutes=str(self.poll_minutes_input.value()),
            )
            set_ai_config(
                enabled='true' if ai_enabled else 'false',
                api_key=ai_key,
                api_base=self.ai_base_input.text().strip() or 'https://api.deepseek.com',
                model=self.ai_model_input.text().strip() or 'deepseek-v4-flash',
            )
        except OSError as e:
            QMessageBox.critical(self, "保存失败", f"无法写入配置文件: {e}")
            return
        # 实时更新内存中的配置常量
        _cfg.reload_business_config()
        self.accept()
