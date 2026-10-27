"""invoice_template_engine 单元测试（ADR D2 · 模板抽取引擎）

覆盖：
    - 模板加载（3 个内置 yaml 全部可载、字段正则编译通过）
    - 匹配：真实感文本（千分位金额、全角冒号），断言 doc_type 与字段值
    - 排除词：文本含排除关键词时不命中
    - 坏 YAML 跳过不崩（tmp_path 写 broken yaml 混入加载目录）
    - 并发：10 线程同时 match_template 无异常、结果一致
    - processor 旁路衔接：模板命中票种入口写「模板抽取」日志，判定不变

运行方式: pytest tests/core/test_invoice_template_engine.py -v
"""
import threading
from pathlib import Path

from invoice_processor.core import invoice_template_engine as engine
from invoice_processor.core.invoice_template_engine import (
    extract_fields,
    load_templates,
    match_template,
)
from invoice_processor.core.processor import InvoiceProcessor

# ═══════════════════════════════════════════════════════════
# 真实感样本文本（含千分位金额、全角冒号）
# ═══════════════════════════════════════════════════════════

_ZHEJIANG_TEXT = (
    '浙江增值税电子普通发票\n'
    '发票号码：24317000000123456789\n'
    '开票日期：2026年10月27日\n'
    '购买方名称：杭州某某科技有限公司\n'
    '价税合计（大写）壹仟贰佰叁拾肆元伍角陆分\n'
    '（小写）￥1,234.56\n'
    '销售方名称：宁波某某机械制造有限公司\n'
)

_RAIL_TEXT = (
    '中国铁路 数字车票（电子客票）\n'
    '旅客姓名：张三\n'
    '车次：G7348\n'
    '乘车日期：2026年10月27日\n'
    '发站：杭州东\n'
    '到站：上海虹桥\n'
    '金额：￥268.00\n'
)

_DIDI_TEXT = (
    '滴滴出行-行程单\n'
    '上车时间：2026-10-27 09:30\n'
    '起点：杭州市西湖区文一西路508号\n'
    '终点：杭州东站\n'
    '里程：12.3公里\n'
    '合计：45.60元\n'
)

# ═══════════════════════════════════════════════════════════
# 模板加载
# ═══════════════════════════════════════════════════════════


def test_load_builtin_templates():
    """3 个内置模板全部可载，字段正则编译通过"""
    templates = load_templates()
    names = {t.name for t in templates}
    assert {'zhejiang_vat', 'highspeed_rail', 'didi_trip'} <= names
    for t in templates:
        assert t.doc_type
        assert t.issuer
        # fields 已在解析时编译，编译失败会在加载阶段抛错
        for patterns in t.fields.values():
            assert patterns  # 至少一条编译后的正则


def test_load_templates_cached():
    """模板列表进程内缓存：二次加载返回同一列表对象"""
    first = load_templates()
    second = load_templates()
    assert first is second


def test_load_templates_broken_yaml_skipped(tmp_path: Path):
    """坏 YAML 单文件跳过并 warning，不整体崩"""
    bad = tmp_path / 'aaa_broken.yaml'
    bad.write_text('issuer: [unclosed', encoding='utf-8')
    good = tmp_path / 'zzz_good.yaml'
    good.write_text(
        'issuer: [测试]\n'
        'doc_type: ok\n'
        'fields:\n'
        "  amount: '金额[：:]\\s*([0-9.]+)'\n",
        encoding='utf-8',
    )
    templates = load_templates(str(tmp_path))
    assert [t.name for t in templates] == ['zzz_good']
    assert templates[0].doc_type == 'ok'


def test_load_templates_missing_dir(tmp_path: Path):
    """目录不存在时返回空列表，不崩"""
    templates = load_templates(str(tmp_path / 'not_exist'))
    assert templates == []

# ═══════════════════════════════════════════════════════════
# 模板匹配 + 字段抽取
# ═══════════════════════════════════════════════════════════


def test_match_zhejiang_and_extract():
    t = match_template(_ZHEJIANG_TEXT)
    assert t is not None and t.doc_type == 'zhejiang_vat'
    fields = extract_fields(_ZHEJIANG_TEXT, t)
    assert fields['invoice_number'] == '24317000000123456789'
    assert fields['invoice_date'] == '2026年10月27日'
    assert fields['amount_tax'] == '1,234.56'  # 千分位保留，不做格式转换
    assert fields['seller_name'] == '宁波某某机械制造有限公司'


def test_match_rail_and_extract():
    t = match_template(_RAIL_TEXT)
    assert t is not None and t.doc_type == 'highspeed_rail'
    fields = extract_fields(_RAIL_TEXT, t)
    assert fields['passenger_name'] == '张三'
    assert fields['train_number'] == 'G7348'
    assert fields['date'] == '2026年10月27日'
    assert fields['amount'] == '268.00'
    assert fields['from_station'] == '杭州东'
    assert fields['to_station'] == '上海虹桥'


def test_match_didi_and_extract():
    t = match_template(_DIDI_TEXT)
    assert t is not None and t.doc_type == 'didi_trip'
    fields = extract_fields(_DIDI_TEXT, t)
    assert fields['date'] == '2026-10-27'
    assert fields['amount'] == '45.60'
    assert fields['mileage'] == '12.3'
    assert fields['start'] == '杭州市西湖区文一西路508号'
    assert fields['end'] == '杭州东站'


def test_match_template_none_when_no_hit():
    assert match_template('完全无关的文本内容') is None
    assert match_template('') is None
    assert match_template(None) is None


def test_match_template_stable_order():
    """匹配按文件名序稳定：浙江命中后不因文本同时含「增值税」漂移到其他模板"""
    t = match_template(_ZHEJIANG_TEXT)
    assert t is not None
    assert t.name == 'zhejiang_vat'


def test_exclude_keyword_blocks_match(tmp_path: Path):
    """文本含排除关键词时不命中"""
    good = tmp_path / 'zzz_x.yaml'
    good.write_text(
        'issuer: [铁路, 车票]\n'
        'doc_type: rail_test\n'
        'exclude_keywords: [汇总单]\n'
        'fields:\n'
        "  amount: '金额[：:]\\s*([0-9.]+)'\n",
        encoding='utf-8',
    )
    templates = load_templates(str(tmp_path))
    assert len(templates) == 1
    hit = match_template('铁路 车票 汇总单 金额：100.00', str(tmp_path))
    assert hit is None  # 排除词命中 → 不匹配
    ok = match_template('铁路 车票 金额：100.00', str(tmp_path))
    assert ok is not None and ok.doc_type == 'rail_test'


def test_extract_fields_keeps_strings():
    """金额/日期保持字符串，不做格式转换"""
    t = match_template(_ZHEJIANG_TEXT)
    assert t is not None
    fields = extract_fields(_ZHEJIANG_TEXT, t)
    assert isinstance(fields['amount_tax'], str)
    assert isinstance(fields['invoice_date'], str)

# ═══════════════════════════════════════════════════════════
# 并发
# ═══════════════════════════════════════════════════════════


def test_match_template_thread_safety():
    """10 线程同时 match_template：无异常、结果一致"""
    engine._clear_cache_for_tests()
    results: list[str | None] = []
    lock = threading.Lock()

    def worker():
        t = match_template(_ZHEJIANG_TEXT)
        with lock:
            results.append(t.doc_type if t else None)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results == ['zhejiang_vat'] * 10


def test_load_templates_thread_safety(tmp_path: Path):
    """并发首次加载同一目录（含缓存竞争）不崩、结果一致"""
    good = tmp_path / 'm.yaml'
    good.write_text(
        'issuer: [并发]\n'
        'doc_type: c\n'
        'fields:\n'
        '  a: "x"\n',
        encoding='utf-8',
    )
    results: list[int] = []
    lock = threading.Lock()

    def worker():
        templates = load_templates(str(tmp_path))
        with lock:
            results.append(len(templates))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results == [1] * 10

# ═══════════════════════════════════════════════════════════
# processor 旁路衔接（模板仅旁路记录）
# ═══════════════════════════════════════════════════════════


class TestProcessorTemplateBypass:
    """模板命中票种入口：伴随抽取写日志；判定与输出不变"""

    def _proc_with_capture(self):
        logs: list[tuple[str, str]] = []
        proc = InvoiceProcessor(
            log_callback=lambda msg, level: logs.append((msg, level))
        )
        return proc, logs

    def test_zhejiang_logs_template_extract(self, tmp_path, monkeypatch):
        proc, logs = self._proc_with_capture()
        src = tmp_path / 'zj.pdf'
        src.write_bytes(b'pdf')
        monkeypatch.setattr(
            proc, 'extract_pdf_text', lambda _p: _ZHEJIANG_TEXT
        )
        # 模板引擎走真实内置模板
        proc.process_zhejiang_invoice(str(src), str(tmp_path))
        infos = [m for m, lv in logs if lv == 'info' and '模板抽取' in m]
        assert len(infos) == 1
        assert 'zhejiang_vat' in infos[0]
        assert '1,234.56' in infos[0]

    def test_didi_logs_template_extract(self, tmp_path, monkeypatch):
        proc, logs = self._proc_with_capture()
        src = tmp_path / 'dd.pdf'
        src.write_bytes(b'pdf')
        monkeypatch.setattr(proc, 'extract_pdf_text', lambda _p: _DIDI_TEXT)
        proc.process_didi_trip(str(src), str(tmp_path))
        infos = [m for m, lv in logs if lv == 'info' and '模板抽取' in m]
        assert len(infos) == 1

    def test_no_hit_no_log(self, tmp_path, monkeypatch):
        proc, logs = self._proc_with_capture()
        src = tmp_path / 'x.pdf'
        src.write_bytes(b'pdf')
        monkeypatch.setattr(
            proc, 'extract_pdf_text', lambda _p: '无关文本'
        )
        proc.process_zhejiang_invoice(str(src), str(tmp_path))
        assert not any('模板抽取' in m for m, _ in logs)

    def test_routing_unchanged_by_templates(self):
        """模板不影响 determine_processor_type 判定（仍按现有注册表关键词）"""
        proc = InvoiceProcessor()
        assert proc.determine_processor_type(
            '浙江通用（电子）发票 发票号码：123'
        ) == proc.process_zhejiang_invoice
        # 模板更宽的命中（浙江增值税电子普通发票）不会改变硬编码路由结果
        assert proc.determine_processor_type(_ZHEJIANG_TEXT) is not None
