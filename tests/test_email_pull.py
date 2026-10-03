"""单元测试：邮箱拉取模块（不依赖网络，仅测纯函数与附件保存/解压逻辑）

运行方式: pytest tests/test_email_pull.py -v
"""
import json
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
    _session_dir_path,
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

    def test_creates_missing_target_dir(self, tmp_path):
        """目标目录不存在时按需创建（会话子目录场景）"""
        target = os.path.join(tmp_path, '拉取_20261002_120000')
        msg = _build_msg([('电子发票.pdf', b'%PDF-1.4 fake', 'application/pdf')])
        saved = _save_attachments(msg, target, [])
        assert len(saved) == 1
        assert os.path.isfile(os.path.join(target, '电子发票.pdf'))

    def test_no_empty_dir_when_nothing_saved(self, tmp_path):
        """整封邮件没有可保存附件时不创建目标目录（不留空批次目录）"""
        target = os.path.join(tmp_path, '拉取_20261002_120000')
        msg = _build_msg([('photo.png', b'pngdata', 'image/png')])
        saved = _save_attachments(msg, target, [])
        assert saved == []
        assert not os.path.isdir(target)

    def test_zip_member_names_sanitized(self, tmp_path):
        """ZIP 成员名含 Windows 非法字符时清洗后落盘，内容完整"""
        import zipfile as _zf
        buf_path = os.path.join(tmp_path, 'tmp.zip')
        with _zf.ZipFile(buf_path, 'w') as zf:
            zf.writestr('report:data.pdf', b'%PDF-1.4 ads-safe')
            zf.writestr('发票<1>.pdf', b'%PDF-1.4 angle')
        with open(buf_path, 'rb') as f:
            zip_bytes = f.read()
        msg = _build_msg([('invoices.zip', zip_bytes, 'application/zip')])
        new_files = []
        errors = []
        saved = _save_attachments(msg, str(tmp_path), new_files, errors)

        assert len(saved) == 2
        assert errors == []
        names = {os.path.basename(p) for p in saved}
        # 清洗后不含非法字符（平台无关断言：检查我们自己的清洗规则）
        for name in names:
            assert not any(ch in name for ch in '\\/:*?"<>|')
        assert 'report_data.pdf' in names
        assert '发票_1_.pdf' in names
        for path in saved:
            assert os.path.getsize(path) > 0

    def test_zip_member_failure_cleans_and_reports(self, tmp_path, monkeypatch):
        """成员级异常（加密/不支持压缩）→ 清理残留、计入 errors、不中止后续成员"""
        import zipfile as _zf
        real_open = _zf.ZipFile.open

        buf_path = os.path.join(tmp_path, 'tmp.zip')
        with _zf.ZipFile(buf_path, 'w') as zf:
            zf.writestr('bad.pdf', b'%PDF-1.4 bad')
            zf.writestr('fine.pdf', b'%PDF-1.4 fine')
        with open(buf_path, 'rb') as f:
            zip_bytes = f.read()

        def selective_open(self, member, mode='r', pwd=None, *, force_zip64=False):
            name = getattr(member, 'filename', member)
            if name == 'bad.pdf':
                raise RuntimeError(f'File {name} is encrypted')
            return real_open(self, member, mode, pwd, force_zip64=force_zip64)

        monkeypatch.setattr(_zf.ZipFile, 'open', selective_open)

        msg = _build_msg([('invoices.zip', zip_bytes, 'application/zip')])
        new_files = []
        errors = []
        saved = _save_attachments(msg, str(tmp_path), new_files, errors)

        # 失败成员：无残留文件、有 error 上报
        assert not os.path.isfile(os.path.join(tmp_path, 'bad.pdf'))
        assert any('bad.pdf' in e for e in errors)
        # 后续成员不受失败影响
        assert [os.path.basename(p) for p in saved] == ['fine.pdf']

    def test_excluded_filename_skipped(self, tmp_path):
        """结账单等排除关键词命中的 PDF 附件不保存、不留目录"""
        target = os.path.join(tmp_path, '拉取_20261003_120000')
        msg = _build_msg([('华住结账单.pdf', b'%PDF-1.4 bill', 'application/pdf')])
        saved = _save_attachments(msg, target, [])
        assert saved == []
        assert not os.path.isdir(target)

    def test_excluded_zip_member_skipped(self, tmp_path):
        """ZIP 内命中排除关键词的成员不落盘，其余 PDF 正常解压"""
        buf_path = os.path.join(tmp_path, 'tmp.zip')
        with zipfile.ZipFile(buf_path, 'w') as zf:
            zf.writestr('发票.pdf', b'%PDF-1.4 invoice')
            zf.writestr('结账单.pdf', b'%PDF-1.4 bill')
        with open(buf_path, 'rb') as f:
            zip_bytes = f.read()
        msg = _build_msg([('huazhu.zip', zip_bytes, 'application/zip')])
        saved = _save_attachments(msg, str(tmp_path), [])
        assert [os.path.basename(p) for p in saved] == ['发票.pdf']
        assert not os.path.isfile(os.path.join(tmp_path, '结账单.pdf'))


class TestSessionDirPath:
    def test_name_format(self, tmp_path):
        path = _session_dir_path(str(tmp_path))
        assert os.path.basename(path).startswith('拉取_')

    def test_unique_on_collision(self, tmp_path):
        first = _session_dir_path(str(tmp_path))
        os.makedirs(first)
        second = _session_dir_path(str(tmp_path))
        assert second != first
        assert os.path.dirname(second) == os.path.dirname(first)


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

    monkeypatch.setattr(
        'invoice_processor.core.email_pull.imaplib.IMAP4_SSL', fake_imap
    )
    result = pull_invoices(
        host='imap.example.com',
        port=993,
        username='user@example.com',
        auth_code='auth',
        inbox_dir=str(tmp_path),
        timeout=2.5,
    )

    assert result['downloaded'] == 0
    assert result['session_dir'] is None
    assert captured == {
        'host': 'imap.example.com',
        'port': 993,
        'timeout': 2.5,
    }


def _make_imap_with_messages(messages):
    """构造带固定邮件列表的 FakeMail。

    messages: [(num_bytes, message_bytes), ...]
    """

    class FakeMail:
        def search(self, charset, query):
            return 'OK', [b' '.join(num for num, _ in messages)]

        def fetch(self, num, spec):
            for msg_num, msg_bytes in messages:
                if msg_num == num:
                    return 'OK', [(b'1', msg_bytes)]
            return 'OK', [None]

        def login(self, username, auth_code):
            pass

        def select(self, mailbox):
            pass

        def logout(self):
            pass

    return FakeMail


def _build_invoice_email(msg_id, attachments):
    """构造完整发票邮件字节（含 From/Subject/Message-ID/附件）"""
    msg = EmailMessage()
    msg['From'] = '[EMAIL]'
    msg['To'] = '[EMAIL]'
    msg['Subject'] = '电子发票'
    msg['Message-ID'] = msg_id
    for name, payload, ctype in attachments:
        main, sub = ctype.split('/', 1)
        msg.add_attachment(payload, maintype=main, subtype=sub, filename=name)
    return msg


def test_pull_invoices_batches_isolated_per_pull(monkeypatch, tmp_path):
    """两次拉取各自落入独立批次目录；无新附件的第三次不产生新目录"""
    mail1 = _build_invoice_email('<m1@x>', [
        ('a.pdf', b'%PDF-1.4 one', 'application/pdf'),
    ])
    mail2 = _build_invoice_email('<m2@x>', [
        ('b.pdf', b'%PDF-1.4 two', 'application/pdf'),
    ])
    fake_mail_cls = _make_imap_with_messages([(b'1', bytes(mail1))])
    monkeypatch.setattr(
        'invoice_processor.core.email_pull.imaplib.IMAP4_SSL',
        lambda host, port, timeout: fake_mail_cls(),
    )
    result1 = pull_invoices(
        username='[EMAIL]', auth_code='auth', inbox_dir=str(tmp_path),
    )
    assert result1['downloaded'] == 1
    assert result1['session_dir'] is not None
    assert os.path.isfile(os.path.join(result1['session_dir'], 'a.pdf'))
    assert os.path.isfile(os.path.join(tmp_path, 'processed_messages.json'))

    fake_mail_cls = _make_imap_with_messages([(b'2', bytes(mail2))])
    monkeypatch.setattr(
        'invoice_processor.core.email_pull.imaplib.IMAP4_SSL',
        lambda host, port, timeout: fake_mail_cls(),
    )
    result2 = pull_invoices(
        username='[EMAIL]', auth_code='auth', inbox_dir=str(tmp_path),
    )
    assert result2['downloaded'] == 1
    assert result2['session_dir'] is not None
    assert result2['session_dir'] != result1['session_dir']
    assert os.path.isfile(os.path.join(result2['session_dir'], 'b.pdf'))

    # 第三次拉取：同一封邮件已去重，无新附件 → 无新批次目录
    fake_mail_cls = _make_imap_with_messages([(b'2', bytes(mail2))])
    monkeypatch.setattr(
        'invoice_processor.core.email_pull.imaplib.IMAP4_SSL',
        lambda host, port, timeout: fake_mail_cls(),
    )
    result3 = pull_invoices(
        username='[EMAIL]', auth_code='auth', inbox_dir=str(tmp_path),
    )
    assert result3['downloaded'] == 0
    assert result3['session_dir'] is None
    batch_dirs = [d for d in os.listdir(tmp_path) if d.startswith('拉取_')]
    assert len(batch_dirs) == 2


def test_pull_invoices_no_empty_dir_on_attachmentless_match(monkeypatch, tmp_path):
    """匹配邮件但无可保存附件（如 PNG 附件）→ 不留空批次目录"""
    # 构造一封白名单发件人、但只有 PNG 附件的邮件
    mail = _build_invoice_email('<m9@x>', [
        ('photo.png', b'pngdata', 'image/png'),
    ])
    fake_mail_cls = _make_imap_with_messages([(b'1', bytes(mail))])
    monkeypatch.setattr(
        'invoice_processor.core.email_pull.imaplib.IMAP4_SSL',
        lambda host, port, timeout: fake_mail_cls(),
    )
    result = pull_invoices(
        username='[EMAIL]', auth_code='auth', inbox_dir=str(tmp_path),
    )
    assert result['downloaded'] == 0
    batch_dirs = [d for d in os.listdir(tmp_path) if d.startswith('拉取_')]
    assert batch_dirs == []


def test_pull_invoices_zip_member_error_not_marked_processed(monkeypatch, tmp_path):
    """ZIP 有成员解压失败 → 邮件不写入去重记录，下次拉取重试"""
    import zipfile as _zf
    buf_path = os.path.join(tmp_path, 'src.zip')
    with _zf.ZipFile(buf_path, 'w') as zf:
        zf.writestr('bad.pdf', b'%PDF-1.4 bad')
        zf.writestr('fine.pdf', b'%PDF-1.4 fine')
    with open(buf_path, 'rb') as f:
        zip_bytes = f.read()

    real_open = _zf.ZipFile.open

    def fail_once_open(self, member, mode='r', pwd=None, *, force_zip64=False):
        """第一次遇到 bad.pdf 抛 RuntimeError，之后恢复正常"""
        name = getattr(member, 'filename', member)
        if name == 'bad.pdf' and not fail_once_open.done:
            fail_once_open.done = True
            raise RuntimeError(f'File {name} is encrypted')
        return real_open(self, member, mode, pwd, force_zip64=force_zip64)

    fail_once_open.done = False
    monkeypatch.setattr(_zf.ZipFile, 'open', fail_once_open)

    mail = _build_invoice_email('<m10@x>', [
        ('invoices.zip', zip_bytes, 'application/zip'),
    ])
    fake_mail_cls = _make_imap_with_messages([(b'1', bytes(mail))])
    monkeypatch.setattr(
        'invoice_processor.core.email_pull.imaplib.IMAP4_SSL',
        lambda host, port, timeout: fake_mail_cls(),
    )

    result1 = pull_invoices(
        username='[EMAIL]', auth_code='auth', inbox_dir=str(tmp_path),
    )
    # fine.pdf 已保存，但 bad.pdf 失败 → errors 上报
    assert result1['downloaded'] == 1
    assert any('bad.pdf' in e for e in result1['errors'])
    # 去重记录不应包含该邮件（可重试）；未标记时文件甚至尚未创建
    record = os.path.join(tmp_path, 'processed_messages.json')
    if os.path.isfile(record):
        with open(record, encoding='utf-8') as f:
            processed = json.load(f)
        assert '<m10@x>' not in processed

    # 第二次拉取：邮件未标记 processed → 整封重试。bad.pdf 成功解压，
    # fine.pdf 重名加序号重新保存（跨批次文件级去重不在本次范围，重试
    # 优先于重复）。全部成员成功 → 邮件这次标记 processed。
    monkeypatch.setattr(_zf.ZipFile, 'open', real_open)
    fake_mail_cls = _make_imap_with_messages([(b'1', bytes(mail))])
    monkeypatch.setattr(
        'invoice_processor.core.email_pull.imaplib.IMAP4_SSL',
        lambda host, port, timeout: fake_mail_cls(),
    )
    result2 = pull_invoices(
        username='[EMAIL]', auth_code='auth', inbox_dir=str(tmp_path),
    )
    assert result2['downloaded'] == 2
    assert result2['errors'] == []
    with open(record, encoding='utf-8') as f:
        processed = json.load(f)
    assert '<m10@x>' in processed
