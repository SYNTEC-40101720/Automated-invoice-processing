"""单元测试：邮箱拉取模块（不依赖网络，仅测纯函数与附件保存/解压逻辑）

运行方式: pytest tests/test_email_pull.py -v
"""
import configparser
import os
import zipfile
from email.message import EmailMessage

from invoice_processor import config_manager
from invoice_processor.core.email_pull import (
    DEFAULT_KEYWORDS,
    DEFAULT_SENDERS,
    _decode,
    _is_invoice_email,
    _save_attachments,
    pull_invoices,
)


def _build_msg(attachments):
    """构造带附件的邮件"""
    msg = EmailMessage()
    for name, payload, ctype in attachments:
        main, sub = ctype.split('/', 1)
        msg.add_attachment(payload, maintype=main, subtype=sub, filename=name)
    return msg


class TestDecode:
    def test_plain_text(self):
        assert _decode('发票') == '发票'

    def test_rfc2047_encoded(self):
        # =?UTF-8?B?5Y+R56Wo?= → 发票
        assert _decode('=?UTF-8?B?5Y+R56Wo?=') == '发票'

    def test_none(self):
        assert _decode(None) == ''


class TestIsInvoiceEmail:
    def test_sender_whitelist(self):
        assert _is_invoice_email(
            'didifapiao@mailgate.xiaojukeji.com', '电子发票',
            DEFAULT_SENDERS, DEFAULT_KEYWORDS,
        )

    def test_subject_keyword(self):
        assert _is_invoice_email(
            'noreply@example.com', '滴滴出行电子发票及行程报销单',
            DEFAULT_SENDERS, DEFAULT_KEYWORDS,
        )

    def test_configured_subject_keyword(self):
        assert _is_invoice_email(
            'noreply@example.com', '差旅凭证', [], ['差旅'],
        )

    def test_non_invoice(self):
        assert not _is_invoice_email(
            'hr@example.com', '会议通知', DEFAULT_SENDERS, DEFAULT_KEYWORDS,
        )

    def test_sender_match_is_not_substring_match(self):
        assert not _is_invoice_email(
            'attacker-didifapiao@mailgate.xiaojukeji.com', '会议通知',
            DEFAULT_SENDERS, DEFAULT_KEYWORDS,
        )


def test_email_keywords_are_trimmed_and_deduplicated(monkeypatch):
    monkeypatch.setattr(
        config_manager,
        'get_email_config',
        lambda: {'keywords': ' 发票,\n报销,发票, 报销 '},
    )

    assert config_manager.get_email_keywords() == ['发票', '报销']


def test_email_auto_process_defaults_to_disabled_for_legacy_config(monkeypatch):
    cfg = configparser.ConfigParser()
    cfg.read_dict({'email': {}})
    monkeypatch.setattr(config_manager, 'load_config', lambda: cfg)

    assert config_manager.get_email_auto_process() is False


class TestSaveAttachments:
    def test_save_pdf(self, tmp_path):
        msg = _build_msg([('电子发票.pdf', b'%PDF-1.4 fake', 'application/pdf')])
        new_files = []
        saved = _save_attachments(msg, str(tmp_path), new_files)
        assert len(saved) == 1
        assert os.path.isfile(os.path.join(tmp_path, '电子发票.pdf'))
        assert len(new_files) == 1

    def test_save_zip_extract_pdf_only(self, tmp_path):
        zip_path = os.path.join(tmp_path, 'tmp.zip')
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('invoice.pdf', b'%PDF-1.4 inside')
            zf.writestr('invoice.ofd', b'ofd')
        with open(zip_path, 'rb') as f:
            zip_bytes = f.read()
        msg = _build_msg([('12306.zip', zip_bytes, 'application/zip')])
        new_files = []
        saved = _save_attachments(msg, str(tmp_path), new_files)
        # 只保留解压出的 PDF；ZIP 原件和 OFD 不进入处理目录
        assert not os.path.isfile(os.path.join(tmp_path, '12306.zip'))
        assert os.path.isfile(os.path.join(tmp_path, 'invoice.pdf'))
        assert not os.path.isfile(os.path.join(tmp_path, 'invoice.ofd'))
        assert len(saved) == 1
        assert len(new_files) == 1

    def test_duplicate_filename_gets_suffix(self, tmp_path):
        with open(os.path.join(tmp_path, 'a.pdf'), 'wb') as f:
            f.write(b'x')
        msg = _build_msg([('a.pdf', b'y', 'application/pdf')])
        new_files = []
        saved = _save_attachments(msg, str(tmp_path), new_files)
        assert os.path.isfile(os.path.join(tmp_path, 'a_1.pdf'))
        assert len(saved) == 1


def test_pull_invoices_passes_bounded_timeout_to_imap(monkeypatch, tmp_path):
    captured = {}

    class FakeMail:
        def login(self, username, auth_code):
            pass

        def select(self, mailbox):
            pass

        def search(self, charset, query):
            return 'OK', [b'']

        def logout(self):
            pass

    def fake_imap(host, port, timeout):
        captured.update(host=host, port=port, timeout=timeout)
        return FakeMail()

    monkeypatch.setattr('invoice_processor.core.email_pull.imaplib.IMAP4_SSL', fake_imap)
    result = pull_invoices(
        host='imap.example.com',
        port=993,
        username='user@example.com',
        auth_code='auth',
        inbox_dir=str(tmp_path),
        timeout=2.5,
    )

    assert result['downloaded'] == 0
    assert captured == {
        'host': 'imap.example.com',
        'port': 993,
        'timeout': 2.5,
    }
