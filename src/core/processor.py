import os
import re
import shutil
import threading
import logging
from datetime import datetime

import pdfplumber
from pypdf import PdfReader, PdfWriter

from ..config import TARGET_TAX_ID


# ═══════════════════════════════════════════════════════════
# 发票处理核心算法类
# ═══════════════════════════════════════════════════════════
class InvoiceProcessor:
    """发票处理核心算法类"""

    def __init__(self):
        self._text_cache = {}
        self._raw_text_cache = {}
        self._cache_lock = threading.Lock()

    @staticmethod
    def _extract_buyer_tax_id(text):
        """提取购买方税号（统一社会信用代码，固定 18 位）

        发票文本含购买方与销售方两个「纳税人识别号」字段，购买方在前。
        策略: 在「销售方」关键字之前的文本中匹配第一个税号，避免误取销售方税号。
        长度固定 18 位，避免吞掉紧随其后的密码区数字。
        """
        if not text:
            return None
        # 截断到「销售方」之前，保留购买方信息块
        buyer_text = re.split(r'销\s*售\s*方', text, maxsplit=1)[0]
        m = re.search(r'(?:纳税人识别号|统一社会信用代码)[:：]\s*([A-Z0-9]{18})', buyer_text)
        return m.group(1) if m else None

    def _extract_raw_text(self, pdf_path):
        """提取PDF原始文本（保留空白，供需要空格分隔的场景使用，带缓存）"""
        with self._cache_lock:
            if pdf_path in self._raw_text_cache:
                return self._raw_text_cache[pdf_path]
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = '\n'.join([page.extract_text() or '' for page in pdf.pages])
                with self._cache_lock:
                    self._raw_text_cache[pdf_path] = text
                return text
        except Exception:
            logging.warning("PDF 文本提取失败: %s", pdf_path, exc_info=True)
            return None

    def extract_pdf_text(self, pdf_path):
        """提取PDF文件文本内容（去空白，带缓存）"""
        with self._cache_lock:
            if pdf_path in self._text_cache:
                return self._text_cache[pdf_path]
        raw = self._extract_raw_text(pdf_path)
        if raw is None:
            return None
        result = re.sub(r'\s+', '', raw)
        with self._cache_lock:
            self._text_cache[pdf_path] = result
        return result

    def _copy_cache_entry(self, src_path, dest_path):
        """复制缓存条目（文件 copy2 后调用，避免对新路径重新解析 PDF）"""
        with self._cache_lock:
            if src_path in self._text_cache:
                self._text_cache[dest_path] = self._text_cache[src_path]
            if src_path in self._raw_text_cache:
                self._raw_text_cache[dest_path] = self._raw_text_cache[src_path]

    def clear_cache(self):
        """清除文本缓存"""
        with self._cache_lock:
            self._text_cache.clear()
            self._raw_text_cache.clear()

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
                self._copy_cache_entry(source_path, dest_path)
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
        注意: 此类汇总单字段间靠空格分隔，需保留空白，故使用 _extract_raw_text 而非去空白的 extract_pdf_text。
        """
        try:
            text = self._extract_raw_text(source_path)
            if not text:
                return None
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
            self._copy_cache_entry(source_path, dest_path)
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
            self._copy_cache_entry(source_path, dest_path)
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

    def post_process(self, output_dir):
        """合并后处理：金额映射 + 待搜索替换 + 税号检查 + PDF合并（单次文本遍历）

        将原 check_tax_ids_in_output_dir 与 merge_pdfs 的两次目录扫描合并为一次：
        对每个 PDF 提取一次文本（命中缓存），同时完成税号检查与合并分类。

        返回: {'amount_map': dict, 'tax_issues': list[str], 'merged': str|None}
        """
        # ① 金额映射（仅文件名解析，快）
        amount_map = self.create_amount_mapping(output_dir)
        # ② 待搜索替换（仅重命名/移动，快）
        self.replace_placeholder_files(output_dir, amount_map)
        # ③④ 单次遍历：税号检查 + 合并分类
        tax_issues = []
        special_invoices = []
        normal_files = []
        异常_dir = os.path.join(output_dir, '税号异常')
        folder_created = False
        for filename in os.listdir(output_dir):
            if not filename.lower().endswith('.pdf'):
                continue
            file_path = os.path.join(output_dir, filename)
            if not os.path.isfile(file_path):
                continue
            text = self.extract_pdf_text(file_path)
            # 税号检查（命中优化1的缓存，无额外解析开销）
            if text:
                tax_id = self._extract_buyer_tax_id(text)
                if tax_id and tax_id != TARGET_TAX_ID:
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
                    tax_issues.append(f'税号异常: {filename} -> {tax_id}，已移动到税号异常文件夹')
                    continue  # 异常文件不参与合并
            # 合并分类
            if ('专用发票' in filename or '高铁票' in filename) or (text and ('专用' in text or '增值税专用发票' in text)):
                special_invoices.append(filename)
            else:
                normal_files.append(filename)
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
                        tax_issues.append(f'税号异常: {filename} -> {tax_id}，已复制到税号异常文件夹（原文件保留在需人工处理）')
        # 合并
        merged = self._merge_classified_pdfs(output_dir, special_invoices, normal_files)
        return {'amount_map': amount_map, 'tax_issues': tax_issues, 'merged': merged}

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

    def _merge_classified_pdfs(self, output_dir, special_invoices, normal_files):
        """合并已分类的PDF文件（使用 PdfWriter，特殊发票奇数页补空白页）

        修复原 merge_pdfs 的 Bug：原实现通过二次 append 整个文件来补奇数页，
        导致内容重复、体积翻倍；现改为 add_blank_page 补单页空白。
        """
        try:
            writer = PdfWriter()
            for filename in special_invoices:
                file_path = os.path.join(output_dir, filename)
                with open(file_path, 'rb') as f:
                    writer.append(PdfReader(f))
                if len(writer.pages) % 2 == 1:
                    writer.add_blank_page()
            for filename in normal_files:
                file_path = os.path.join(output_dir, filename)
                with open(file_path, 'rb') as f:
                    writer.append(PdfReader(f))
            merged_path = os.path.join(output_dir, '合并结果.pdf')
            with open(merged_path, 'wb') as f:
                writer.write(f)
            writer.close()
            return merged_path
        except Exception:
            logging.error("PDF 合并失败: %s", output_dir, exc_info=True)
            return None

    def merge_pdfs(self, output_dir):
        """合并PDF文件（向后兼容包装：自行分类后委托 _merge_classified_pdfs）"""
        special_invoices = []
        normal_files = []
        for filename in os.listdir(output_dir):
            if not filename.lower().endswith('.pdf'):
                continue
            file_path = os.path.join(output_dir, filename)
            if not os.path.isfile(file_path):
                continue
            text = self.extract_pdf_text(file_path)
            if ('专用发票' in filename or '高铁票' in filename) or (text and ('专用' in text or '增值税专用发票' in text)):
                special_invoices.append(filename)
            else:
                normal_files.append(filename)
        return self._merge_classified_pdfs(output_dir, special_invoices, normal_files)
