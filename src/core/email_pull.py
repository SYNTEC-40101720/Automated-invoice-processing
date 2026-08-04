"""邮箱发票自动拉取模块（IMAP）

从指定邮箱（默认 QQ 邮箱 imap.qq.com:993）拉取发票邮件附件到本地「发票收件箱」目录。

- 登录：账号 + 授权码（QQ 邮箱 IMAP 授权码，非登录密码）
- 过滤：发件方白名单 或 主题含关键字（发票/行程单/报销）
- 附件：下载 PDF / ZIP；ZIP 自动解压并只保留 PDF
- 去重：本地 processed_messages.json 记录已处理 message_id，避免重复下载
- 安全：默认不修改邮件状态（BODY.PEEK 读取）；可选 mark_seen 标记已读
- 约束：本模块不依赖 Qt，可独立运行/测试
"""
import imaplib
import json
import logging
import os
import re
import zipfile
from datetime import datetime, timedelta
from email import message_from_bytes
from email.header import decode_header

logger = logging.getLogger(__name__)

# 常见发票发件方（可按需扩展）
DEFAULT_SENDERS = [
    '12306@rails.com.cn',                          # 高铁票
    'didifapiao@mailgate.xiaojukeji.com',          # 滴滴
    'fapiao@mailgate.hongyibo.com.cn',             # 网约车
    'invoice@invoice01.huazhuhotels.com',          # 华住酒店
    'service@invoice.txffp.com',                   # 通行费
]
# 主题关键字兜底
DEFAULT_KEYWORDS = ['发票', '行程单', '报销']

# 去重记录文件名（存放在收件箱目录内）
_RECORD_FILENAME = 'processed_messages.json'


def _decode(value):
    """解码邮件头（兼容 RFC2047 编码）"""
    if not value:
        return ''
    out = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            try:
                out.append(text.decode(charset or 'utf-8', errors='replace'))
            except (LookupError, ValueError):
                out.append(text.decode('utf-8', errors='replace'))
        else:
            out.append(text)
    return ''.join(out)


def _load_processed(record_path: str) -> set:
    """读取已处理的 message_id 集合"""
    if os.path.isfile(record_path):
        try:
            with open(record_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(data if isinstance(data, list) else [])
        except (OSError, ValueError):
            logger.warning('读取去重记录失败，将重建: %s', record_path)
    return set()


def _save_processed(record_path: str, processed: set) -> None:
    """持久化已处理的 message_id"""
    try:
        with open(record_path, 'w', encoding='utf-8') as f:
            json.dump(sorted(processed), f, ensure_ascii=False, indent=1)
    except OSError as e:
        logger.warning('保存去重记录失败: %s', e)


def _is_invoice_email(from_addr: str, subject: str,
                      senders: list, keywords: list) -> bool:
    """判断邮件是否为发票邮件（发件方白名单 或 主题关键字）"""
    from_lower = from_addr.lower()
    if any(s in from_lower for s in senders):
        return True
    return any(kw in subject for kw in keywords)


def _unique_path(directory: str, filename: str) -> str:
    """重名时自动追加序号（_1, _2 ...）"""
    dest = os.path.join(directory, filename)
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(filename)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(directory, f'{base}_{i}{ext}')
        i += 1
    return dest


def _save_attachments(msg, inbox_dir: str, new_files: list) -> list:
    """保存邮件附件（PDF/ZIP），ZIP 解压只留 PDF。返回保存路径列表"""
    saved = []
    for part in msg.walk():
        filename = part.get_filename()
        if not filename:
            continue
        filename = _decode(filename)
        content_type = part.get_content_type()
        is_pdf = content_type == 'application/pdf' or filename.lower().endswith('.pdf')
        is_zip = content_type in ('application/zip', 'application/x-zip-compressed') \
            or filename.lower().endswith('.zip')
        if not (is_pdf or is_zip):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        safe = re.sub(r'[\\/:*?"<>|]', '_', filename)
        dest = _unique_path(inbox_dir, safe)
        with open(dest, 'wb') as f:
            f.write(payload)
        new_files.append(dest)
        saved.append(dest)
        logger.info('已保存附件: %s', dest)

        if is_zip:
            try:
                with zipfile.ZipFile(dest) as zf:
                    for name in zf.namelist():
                        if name.lower().endswith('.pdf'):
                            target = _unique_path(inbox_dir, os.path.basename(name))
                            with zf.open(name) as src, open(target, 'wb') as out:
                                out.write(src.read())
                            new_files.append(target)
                            saved.append(target)
                            logger.info('ZIP 内 PDF 已解压: %s', target)
            except (zipfile.BadZipFile, OSError) as e:
                logger.warning('ZIP 解压失败 %s: %s', dest, e)
    return saved


def pull_invoices(host='imap.qq.com', port=993, username='', auth_code='',
                  inbox_dir='', days_back=30, senders=None, keywords=None,
                  mark_seen=False, record_path=None) -> dict:
    """从邮箱拉取发票附件

    Args:
        host: IMAP 服务器（默认 imap.qq.com）
        port: IMAP SSL 端口（默认 993）
        username: 邮箱账号
        auth_code: IMAP 授权码（非登录密码）
        inbox_dir: 本地发票收件箱目录（不存在则创建）
        days_back: 只拉取最近 N 天的邮件
        senders: 发票发件方白名单
        keywords: 主题关键字
        mark_seen: 是否标记已读
        record_path: 去重记录文件路径（默认收件箱目录内）

    Returns:
        {'downloaded': int, 'new_files': list, 'errors': list, 'total_scanned': int}

    Raises:
        ValueError: 账号/授权码/收件箱目录未配置
    """
    if not username or not auth_code:
        raise ValueError('未配置邮箱账号或授权码（config.ini [email] 段）')
    if not inbox_dir:
        raise ValueError('未配置发票收件箱目录（config.ini [email] inbox_dir）')

    os.makedirs(inbox_dir, exist_ok=True)
    senders = senders or DEFAULT_SENDERS
    keywords = keywords or DEFAULT_KEYWORDS
    record_path = record_path or os.path.join(inbox_dir, _RECORD_FILENAME)
    processed = _load_processed(record_path)
    new_files: list = []
    errors: list = []
    total_scanned = 0

    since = (datetime.now() - timedelta(days=days_back)).strftime('%d-%b-%Y')

    mail = imaplib.IMAP4_SSL(host, port)
    try:
        mail.login(username, auth_code)
        mail.select('INBOX')
        typ, data = mail.search(None, f'(SINCE "{since}")')
        if typ != 'OK' or not data or not data[0]:
            logger.info('未搜索到邮件（最近 %d 天）', days_back)
            return {'downloaded': 0, 'new_files': [], 'errors': errors,
                    'total_scanned': 0}

        msg_nums = data[0].split()
        total_scanned = len(msg_nums)
        # 倒序处理：最新邮件优先
        for num in reversed(msg_nums):
            try:
                # 先读头部（BODY.PEEK 不改变已读状态）
                typ, head_data = mail.fetch(num, '(BODY.PEEK[HEADER])')
                if typ != 'OK' or not head_data or head_data[0] is None:
                    continue
                header_msg = message_from_bytes(head_data[0][1])
                from_addr = _decode(header_msg.get('From', ''))
                subject = _decode(header_msg.get('Subject', ''))
                if not _is_invoice_email(from_addr, subject, senders, keywords):
                    continue

                # 读取完整邮件取附件
                typ, full_data = mail.fetch(num, '(BODY.PEEK[])')
                if typ != 'OK' or not full_data or full_data[0] is None:
                    continue
                full_msg = message_from_bytes(full_data[0][1])
                msg_id = full_msg.get('Message-ID') or f'num_{num.decode()}'
                if msg_id in processed:
                    continue

                saved = _save_attachments(full_msg, inbox_dir, new_files)
                if saved:
                    processed.add(msg_id)
                    _save_processed(record_path, processed)
                    logger.info('已处理: %s（%s）', subject, from_addr)
                if mark_seen:
                    mail.store(num, '+FLAGS', '\\Seen')
            except Exception as e:  # 单封失败不中断
                errors.append(f'处理邮件 {num.decode()} 失败: {e}')
                logger.warning('处理邮件失败: %s', e)
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    return {
        'downloaded': len(new_files),
        'new_files': new_files,
        'errors': errors,
        'total_scanned': total_scanned,
    }
