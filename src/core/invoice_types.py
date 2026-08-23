"""发票类型注册与分发

职责：
    - 以注册表模式维护「文本关键字 → 处理函数」的映射（顺序敏感，越具体越靠前）
    - 提供各发票类型的具体处理逻辑（按 (发票号, 金额) 提取并命名为 发票号-金额.pdf）
    - determine_processor_type：根据文本返回首个命中的处理方法

处理函数接收 processor 外观，以便复用其文本提取 / 输出写入能力，
从而保持函数本身无状态、可独立测试。
"""
import os
import re
import shutil
from collections.abc import Callable

# 发票类型注册表：[(keywords, method_name), ...]
# 顺序敏感 —— 越具体越靠前，通用 fallback 放最后
_TYPE_REGISTRY: list[tuple[tuple[str, ...], str]] = []


def register_type(*keywords: str):
    """装饰器：注册发票类型处理器及其匹配关键字

    用法：
        @register_type('浙江通用（电子）发票', '宁波通用（电子）发票')
        def process_zhejiang_invoice(processor, source_path, output_dir): ...
    """
    def deco(fn):
        _TYPE_REGISTRY.append((keywords, fn.__name__))
        return fn
    return deco


def determine_processor_type(processor, text: str) -> Callable | None:
    """根据文本内容确定发票类型，返回 processor 上首个命中的处理方法

    遍历 _TYPE_REGISTRY，按注册顺序匹配关键字，返回 getattr(processor, method_name)。
    新增类型只需用 @register_type 装饰对应函数，无需修改本函数。
    """
    for keywords, method_name in _TYPE_REGISTRY:
        if any(kw in text for kw in keywords):
            return getattr(processor, method_name)
    return None


@register_type('浙江通用（电子）发票', '宁波通用（电子）发票')
def process_zhejiang_invoice(
    processor, source_path: str, output_dir: str
) -> str | None:
    """处理浙江/宁波通用电子发票"""
    return processor._process_invoice(
        source_path, output_dir,
        r'发票号码[:：]\s*(\d+)',
        r'（小写）\s*([\d.]+)',
        "ZJ",
    )


@register_type('江苏省车辆通行费票据（电子）')
def process_jiangsu_toll(processor, source_path: str, output_dir: str) -> str | None:
    """处理江苏通行费票据"""
    return processor._process_invoice(
        source_path, output_dir,
        r'票据号码[：:]\s*(\d{10})',
        r'（小写）\s*([\d.]+\d{2})',
        "JST",
    )


@register_type('江苏省车辆通行费电子票据行程单')
def process_jiangsu_invoice(processor, source_path: str, output_dir: str) -> str | None:
    """处理江苏车辆通行费电子票据行程单"""
    return processor._process_invoice(
        source_path, output_dir,
        r'发票号码\s*(\d+)',
        r'累计金额\(元\)\s*([\d.]+)',
        "JS",
    )


@register_type('中国铁路', '二等座', '一等座')
def process_highspeed_rail(processor, source_path: str, output_dir: str) -> str | None:
    """处理高铁票"""
    return processor._process_invoice(
        source_path, output_dir,
        r'(?:电子发票号码|发票号码)[\s:：]*([A-Z0-9]{20})',
        r'(?:金额|￥)\s*([\d,.]+)',
        "H",
        lambda x: x.replace(',', ''),
    )


@register_type('滴滴出行-行程单', '—行程单')
def process_didi_trip(processor, source_path: str, output_dir: str) -> str | None:
    """处理滴滴行程单"""
    try:
        text = processor.extract_pdf_text(source_path)
        amount_match = re.search(r'合计([\d.,]+)元', text)
        if amount_match:
            clean_amount = "{:.2f}".format(
                float(amount_match.group(1).replace(',', ''))
            )
            new_filename = f"待搜索-{clean_amount}行程单.pdf"
            dest_path = os.path.join(output_dir, new_filename)
            if not processor._claim_output_name(new_filename, source_path, output_dir):
                return dest_path  # 重复，跳过
            shutil.copy2(source_path, dest_path)
            processor._copy_cache_entry(source_path, dest_path)
            return dest_path
        else:
            return None
    except Exception:
        processor._log_core(f"滴滴行程单处理失败: {source_path}", level='warning')
        return None


@register_type('收费公路通行费电子票据汇总单')
def process_toll_summary(processor, source_path: str, output_dir: str) -> str | None:
    """处理收费公路通行费电子票据汇总单（按行程索引）

    提取第一张票据的号码和含税金额，命名为 {票据号码}-{金额}行程单.pdf
    支持两种票据格式:
    - 传统票据: 12位票据代码 + 8位票据号码 + 金额
    - 数电发票: * + 20位发票号码 + 金额
    注意: 此类汇总单字段间靠空格分隔，需保留空白，故使用
    _extract_raw_text 而非去空白的 extract_pdf_text。
    """
    try:
        text, _ = processor._extract_raw_text(source_path)
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
        new_filename = f"{invoice_no}-{processor._normalize_amount(amount)}行程单.pdf"
        dest_path = os.path.join(output_dir, new_filename)
        if not processor._claim_output_name(new_filename, source_path, output_dir):
            return dest_path  # 重复，跳过
        shutil.copy2(source_path, dest_path)
        processor._copy_cache_entry(source_path, dest_path)
        return dest_path
    except Exception:
        processor._log_core(f"通行费汇总单处理失败: {source_path}", level='warning')
        return None


@register_type('电子发票', '电 子 发 票', '发票号码', '票据号码')
def process_general_invoice(processor, source_path: str, output_dir: str) -> str | None:
    """处理通用电子发票（fallback）"""
    try:
        text = processor.extract_pdf_text(source_path)
        if not text:
            return None
        pattern1 = re.search(r'(?:发票号码|发\s*票\s*号\s*码)[\s:：]*(\d{8,20})', text)
        # fallback: 在金额关键字附近匹配 20 位连续数字，降低误匹配概率
        pattern2 = re.search(
            r'(?:金额|合计|价税|小写).{0,30}'
            r'(?<!\d)(\d{20})(?!\d)',
            text,
        )
        invoice_match = pattern1 if pattern1 else pattern2
        amount_match = re.search(
            r'[（(]\s*小写\s*[）)]\s*[:：]?\s*[¥￥]?\s*([\d.]+)',
            text,
        )
        if not (invoice_match and amount_match):
            return None
        return processor._generate_output_file(
            source_path, output_dir,
            invoice_match.group(1), amount_match.group(1), "F"
        )
    except Exception:
        processor._log_core(f"通用发票处理失败: {source_path}", level='warning')
        return None
