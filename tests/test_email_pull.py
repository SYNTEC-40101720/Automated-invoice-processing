"""单元测试：邮箱拉取模块（不依赖网络，仅测纯函数与附件保存/解压逻辑）

运行方式: pytest tests/test_email_pull.py -v
"""
import os
import zipfile
from email.message import EmailMessage

from src.core.email_pull import (
    DEFAULT_KEYWORDS,
    DEFAULT_SENDERS,
    _decode,
    _is_invoice_email,
    _save_attachments,
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

    def test_non_invoice(self):
        assert not _is_invoice_email(
            'hr@example.com', '会议通知', DEFAULT_SENDERS, DEFAULT_KEYWORDS,
        )


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
        # ZIP 本体 + 解压出的 PDF；OFD 不保留
        assert os.path.isfile(os.path.join(tmp_path, '12306.zip'))
        assert os.path.isfile(os.path.join(tmp_path, 'invoice.pdf'))
        assert not os.path.isfile(os.path.join(tmp_path, 'invoice.ofd'))
        assert len(saved) == 2

    def test_duplicate_filename_gets_suffix(self, tmp_path):
        with open(os.path.join(tmp_path, 'a.pdf'), 'wb') as f:
            f.write(b'x')
        msg = _build_msg([('a.pdf', b'y', 'application/pdf')])
        new_files = []
        saved = _save_attachments(msg, str(tmp_path), new_files)
        assert os.path.isfile(os.path.join(tmp_path, 'a_1.pdf'))
        assert len(saved) == 1
