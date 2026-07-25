import os
import re
import shutil
import threading
import logging
from datetime import datetime

import pdfplumber
from PyPDF2 import PdfMerger

from ..config import TARGET_TAX_ID


# ═══════════════════════════════════════════════════════════
# 发票处理核心算法类
# ═══════════════════════════════════════════════════════════
class InvoiceProcessor:
    """发票处理核心算法类"""

    def __init__(self):
        self._text_cache = {}
        self._cache_lock = threading.Lock()

    def extract_pdf_text(self, pdf_path):
        """提取PDF文件文本内容（带缓存）"""
        with self._cache_lock:
            if pdf_path in self._text_cache:
                return self._text_cache[pdf_path]
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = '\n'.join([page.extract_text() or '' for page in pdf.pages])
                result = re.sub(r'\s+', '', text)
                with self._cache_lock:
                    self._text_cache[pdf_path] = result
                return result
        except Exception:
            logging.warning("PDF 文本提取失败: %s", pdf_path, exc_info=True)
            return None

    def clear_cache(self):
        """清除文本缓存"""
        with self._cache_lock:
            self._text_cache.clear()

    def process_zhejiang_invoice(self, source_path, output_dir):
        """处理浙江/宁波通用电子发票"""
        return self._process_invoice(
            source_path, output_dir,
            r'发票号码[:：]\s*(\d+)',
            r'（小写）\s+([\d.]+)',
            "ZJ"
        )

    def process_jiangsu_toll(self, source_path, output_dir):
        """处理江苏通行费票据"""
        return self._process_invoice(
            source_path, output_dir,
            r'票据号码[：:]\s*(\d{10})',
            r'（小写）\s*([\d.]+\d{2})',
            "JST"
        )

    def process_general_invoice(self, source_path, output_dir):
        """处理通用电子发票"""
        try:
            text = self.extract_pdf_text(source_path)
            if not text:
                return None
            pattern1 = re.search(r'(?:发票号码|发\s*票\s*号\s*码)[\s:：]*(\d{8,20})', text)
            pattern2 = re.search(r'(?<!\d)(\d{20})(?!\d)', text)
            invoice_match = pattern1 if pattern1 else pattern2
            amount_match = re.search(r'[（(]\s*小写\s*[）)]\s*[:：]?\s*[¥￥]?\s*([\d.]+)', text)
            if not (invoice_match and amount_match):
                return None
            return self._generate_output_file(
                source_path, output_dir,
                invoice_match.group(1), amount_match.group(1), "F"
            )
        except Exception:
            logging.warning("通用发票处理失败: %s", source_path, exc_info=True)
            return None

    def process_highspeed_rail(self, source_path, output_dir):
        """处理高铁票"""
        return self._process_invoice(
            source_path, output_dir,
            r'(?:电子发票号码|发票号码)[\s:：]*([A-Z0-9]{20})',
            r'(?:金额|￥)\s*([\d,.]+)',
            "H",
            lambda x: x.replace(',', '')
        )

    def process_jiangsu_invoice(self, source_path, output_dir):
        """处理江苏车辆通行费电子票据行程单"""
        return self._process_invoice(
            source_path, output_dir,
            r'发票号码\s+(\d+)',
            r'累计金额\(元\)\s+([\d.]+)',
            "JS"
        )

    def process_didi_trip(self, source_path, output_dir):
        """处理滴滴行程单"""
        try:
            text = self.extract_pdf_text(source_path)
            amount_match = re.search(r'合计([\d.,]+)元', text)
            if amount_match:
                clean_amount = "{:.2f}".format(float(amount_match.group(1).replace(',', '')))
                new_filename = f"待搜索-{clean_amount}行程单.pdf"
                dest_path = os.path.join(output_dir, new_filename)
                shutil.copy2(source_path, dest_path)
                return dest_path
            else:
                return None
        except Exception:
            logging.warning("滴滴行程单处理失败: %s", source_path, exc_info=True)
            return None

    def process_toll_summary(self, source_path, output_dir):
        """处理收费公路通行费电子票据汇总单（按行程索引）

        提取第一张票据的号码和含税金额，命名为 {票据号码}-{金额}行程单.pdf
        支持两种票据格式:
        - 传统票据: 12位票据代码 + 8位票据号码 + 金额
        - 数电发票: * + 20位发票号码 + 金额
        注意: 此类汇总单字段间靠空格分隔，需保留空白，故不使用 extract_pdf_text 的去空白结果。
        """
        try:
            with pdfplumber.open(source_path) as pdf:
                text = '\n'.join([page.extract_text() or '' for page in pdf.pages])
            # 在 "票据信息" 锚点后, 优先匹配传统票据(12位代码 + 8位号码 + 金额)
            m = re.search(r'票据信息.*?(\d{12})\s+(\d{8})\s+([\d.]+)', text, re.DOTALL)
            if m:
                invoice_no = m.group(2)
                amount = m.group(3)
            else:
                # 数电发票格式: * + 20位号码 + 金额
                m = re.search(r'票据信息.*?\*\s*(\d{20})\s+([\d.]+)', text, re.DOTALL)
                if m:
                    invoice_no = m.group(1)
                    amount = m.group(2)
                else:
                    return None
            new_filename = f"{invoice_no}-{amount}行程单.pdf"
            dest_path = os.path.join(output_dir, new_filename)
            shutil.copy2(source_path, dest_path)
            return dest_path
        except Exception:
            logging.warning("通行费汇总单处理失败: %s", source_path, exc_info=True)
            return None

    def _process_invoice(self, source_path, output_dir, invoice_pattern, amount_pattern, prefix, amount_processor=None):
        """发票处理通用方法"""
        try:
            text = self.extract_pdf_text(source_path)
            if not text:
                return None
            invoice_match = re.search(invoice_pattern, text)
            amount_match = re.search(amount_pattern, text)
            if not (invoice_match and amount_match):
                return None
            invoice_no = invoice_match.group(1)
            amount = amount_match.group(1)
            if amount_processor:
                amount = amount_processor(amount)
            return self._generate_output_file(source_path, output_dir, invoice_no, amount, prefix)
        except Exception:
            logging.warning("发票处理失败: %s", source_path, exc_info=True)
            return None

    def _generate_output_file(self, source_path, output_dir, invoice_no, amount, prefix):
        """生成输出文件（invoice_no/amount 为已提取的字符串）"""
        try:
            new_filename = f"{invoice_no}-{amount}"
            if prefix == "JS":
                new_filename += "行程单.pdf"
            elif prefix == "H":
                new_filename += "高铁票.pdf"
            else:
                new_filename += ".pdf"
            dest_path = os.path.join(output_dir, new_filename)
            shutil.copy2(source_path, dest_path)
            return dest_path
        except Exception:
            logging.warning("输出文件生成失败: %s", source_path, exc_info=True)
            return None

    def create_amount_mapping(self, folder_path):
        """创建金额映射表"""
        amount_map = {}
        for filename in os.listdir(folder_path):
            if filename.startswith('待搜索'):
                continue
            parts = filename.split('-', 1)
            if len(parts) >= 2:
                invoice_part, amount_part = parts
                amount_match = re.match(r'^(\d+\.\d{2})(?:行程单)?\.pdf$', amount_part)
                if amount_match:
                    amount = amount_match.group(1)
                    amount_map[amount] = invoice_part
        return amount_map

    def check_tax_ids_in_output_dir(self, output_dir):
        """检查所有文件的税号（主目录 + 需人工处理子目录）

        主目录中的异常文件移动到 税号异常/ 子目录；
        需人工处理/ 中的异常文件复制到 税号异常/（保留原文件便于人工处理）。
        """
        异常_dir = os.path.join(output_dir, '税号异常')
        folder_created = False
        # 扫描主目录（异常文件移动）
        for filename in os.listdir(output_dir):
            if not filename.lower().endswith('.pdf'):
                continue
            file_path = os.path.join(output_dir, filename)
            if not os.path.isfile(file_path):
                continue
            text = self.extract_pdf_text(file_path)
            if not text:
                continue
            tax_id_match = re.search(r'(?:纳税人识别号|统一社会信用代码)[:：]\s*([A-Z0-9]{15,20})', text)
            if tax_id_match:
                tax_id = tax_id_match.group(1)
                if tax_id != TARGET_TAX_ID:
                    if not folder_created:
                        os.makedirs(异常_dir, exist_ok=True)
                        folder_created = True
                    dest_path = os.path.join(异常_dir, filename)
                    counter = 1
                    while os.path.exists(dest_path):
                        name, ext = os.path.splitext(filename)
                        dest_path = os.path.join(异常_dir, f'{name}_{counter}{ext}')
                        counter += 1
                    shutil.move(file_path, dest_path)
                    yield f'税号异常: {filename} -> {tax_id}，已移动到税号异常文件夹'
        # 扫描 需人工处理/ 子目录（异常文件复制，保留原文件）
        manual_dir = os.path.join(output_dir, '需人工处理')
        if os.path.isdir(manual_dir):
            for filename in os.listdir(manual_dir):
                if not filename.lower().endswith('.pdf'):
                    continue
                file_path = os.path.join(manual_dir, filename)
                if not os.path.isfile(file_path):
                    continue
                text = self.extract_pdf_text(file_path)
                if not text:
                    continue
                tax_id_match = re.search(r'(?:纳税人识别号|统一社会信用代码)[:：]\s*([A-Z0-9]{15,20})', text)
                if tax_id_match:
                    tax_id = tax_id_match.group(1)
                    if tax_id != TARGET_TAX_ID:
                        if not folder_created:
                            os.makedirs(异常_dir, exist_ok=True)
                            folder_created = True
                        dest_path = os.path.join(异常_dir, filename)
                        counter = 1
                        while os.path.exists(dest_path):
                            name, ext = os.path.splitext(filename)
                            dest_path = os.path.join(异常_dir, f'{name}_{counter}{ext}')
                            counter += 1
                        shutil.copy2(file_path, dest_path)
                        yield f'税号异常: {filename} -> {tax_id}，已复制到税号异常文件夹（原文件保留在需人工处理）'

    def replace_placeholder_files(self, folder_path, amount_map):
        """替换待搜索文件（匹配失败的移动到 需人工处理/ 子目录）"""
        manual_dir = os.path.join(folder_path, '需人工处理')
        for filename in os.listdir(folder_path):
            if not filename.startswith('待搜索'):
                continue
            parts = filename.split('-', 1)
            if len(parts) < 2:
                continue
            _, remainder = parts
            amount_match = re.match(r'^(\d+\.\d{2})(?:行程单)?\.pdf$', remainder)
            if not amount_match:
                continue
            amount = amount_match.group(1)
            invoice_no = amount_map.get(amount)
            old_path = os.path.join(folder_path, filename)
            if invoice_no:
                new_name = f"{invoice_no}-{remainder}"
                new_path = os.path.join(folder_path, new_name)
                if not os.path.exists(new_path):
                    os.rename(old_path, new_path)
            else:
                # 匹配失败: 移动到需人工处理子目录
                os.makedirs(manual_dir, exist_ok=True)
                new_path = os.path.join(manual_dir, filename)
                counter = 1
                while os.path.exists(new_path):
                    name, ext = os.path.splitext(filename)
                    new_path = os.path.join(manual_dir, f'{name}_{counter}{ext}')
                    counter += 1
                shutil.move(old_path, new_path)

    def determine_processor_type(self, text):
        """根据文本内容确定发票类型"""
        if '浙江通用（电子）发票' in text or '宁波通用（电子）发票' in text:
            return self.process_zhejiang_invoice
        elif '江苏省车辆通行费票据（电子）' in text:
            return self.process_jiangsu_toll
        elif '江苏省车辆通行费电子票据行程单' in text:
            return self.process_jiangsu_invoice
        elif '中国铁路' in text or '二等座' in text or '一等座' in text:
            return self.process_highspeed_rail
        elif '滴滴出行-行程单' in text or '—行程单' in text:
            return self.process_didi_trip
        elif '收费公路通行费电子票据汇总单' in text:
            return self.process_toll_summary
        elif '电子发票' in text or '电 子 发 票' in text or '发票号码' in text or '票据号码' in text:
            return self.process_general_invoice
        return None

    def create_output_directory(self, base_dir):
        """创建输出目录"""
        timestamp_dir = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.join(base_dir, timestamp_dir)
        try:
            os.makedirs(output_dir, exist_ok=True)
            return output_dir
        except PermissionError:
            output_dir = os.path.join(os.path.expanduser('~'), 'Desktop', '发票输出', timestamp_dir)
            os.makedirs(output_dir, exist_ok=True)
            return output_dir

    def merge_pdfs(self, output_dir):
        """合并PDF文件"""
        try:
            merger = PdfMerger()
            special_invoices = []
            normal_files = []
            for filename in os.listdir(output_dir):
                if filename.endswith('.pdf'):
                    file_path = os.path.join(output_dir, filename)
                    if not os.path.isfile(file_path):
                        continue
                    text = self.extract_pdf_text(file_path)
                    if ('专用发票' in filename or '高铁票' in filename) or (text and ('专用' in text or '增值税专用发票' in text)):
                        special_invoices.append(filename)
                    else:
                        normal_files.append(filename)
            for filename in special_invoices:
                file_path = os.path.join(output_dir, filename)
                merger.append(file_path)
                if len(merger.pages) % 2 == 1:
                    merger.append(file_path)
            for filename in normal_files:
                file_path = os.path.join(output_dir, filename)
                merger.append(file_path)
            merged_path = os.path.join(output_dir, '合并结果.pdf')
            merger.write(merged_path)
            merger.close()
            return merged_path
        except Exception:
            logging.error("PDF 合并失败: %s", output_dir, exc_info=True)
            return None
