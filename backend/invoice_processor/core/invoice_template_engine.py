"""发票模板抽取引擎（invoice2data 模式，ADR D2）

职责：
    - load_templates(dir_path=None)：扫描 core/templates/*.yaml，解析 issuer/doc_type/
      fields/exclude_keywords 结构；单文件解析失败跳过并 warning，不整体崩溃。
    - match_template(text)：按文件名稳定顺序匹配 issuer 全命中且排除词未命中的模板。
    - extract_fields(text, template)：按字段正则（单条或多条候选）抽取，返回首个成功
      捕获组；金额/日期保持字符串，不做格式转换（由调用方决定）。

衔接策略（ADR D2 · 兜底优先）：
    模板引擎当前仅旁路记录：process_xxx 入口处伴随抽取并写「模板抽取」日志，
    不改变类型判定与处理结果；模板稳定后再评估接管硬编码抽取。

线程安全：
    模板列表进程内缓存 + 模块级锁；任务线程并发调用 load/match 安全。
"""
import logging
import os
import re
import threading
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)

# 内置模板目录：core/templates/
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')

_LOCK = threading.Lock()
# 进程内模板缓存：dir_path（规范化后）→ 已解析模板列表
_CACHE: dict[str, list['TemplateMatch']] = {}


@dataclass
class TemplateMatch:
    """一条已解析的模板"""
    name: str
    doc_type: str
    issuer: tuple[str, ...]
    # 字段名 → 编译后的候选正则列表（多候选时取第一个命中的捕获组）
    fields: dict[str, list[re.Pattern[str]]] = field(default_factory=dict)
    exclude_keywords: tuple[str, ...] = ()


def load_templates(dir_path: str | None = None) -> list[TemplateMatch]:
    """加载模板目录下所有 *.yaml，按文件名排序，返回已解析模板列表

    - 每个模板 dict 结构：issuer（关键词列表，全部命中才算）、doc_type（对应现有
      票种标识）、fields（字段名→单条或多条 regex，带命名组或整段捕获）、
      exclude_keywords（可选，命中任一则不匹配）。
    - 单文件加载失败（YAML 语法错误 / 结构缺失）跳过并 warning，不整体崩。
    - 模板列表进程内缓存 + 模块锁（任务线程并发调用安全）。
    """
    resolved = os.path.normpath(
        dir_path if dir_path is not None else _TEMPLATE_DIR
    )
    with _LOCK:
        cached = _CACHE.get(resolved)
        if cached is not None:
            return cached

        templates: list[TemplateMatch] = []
        if os.path.isdir(resolved):
            filenames = sorted(
                f for f in os.listdir(resolved)
                if f.lower().endswith(('.yaml', '.yml'))
            )
            for filename in filenames:
                try:
                    parsed = _parse_template_file(os.path.join(resolved, filename))
                except Exception as exc:  # noqa: BLE001 — 单模板坏文件不整体崩
                    logger.warning('模板加载失败（跳过）: %s - %s', filename, exc)
                    continue
                if parsed is not None:
                    templates.append(parsed)
        _CACHE[resolved] = templates
        return templates


def _parse_template_file(path: str) -> TemplateMatch | None:
    """解析单个 YAML 模板文件为 TemplateMatch"""
    # 显式 UTF-8 读取（Windows 默认 cp936 环境下必须显式指定）
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError('模板根必须是 dict')
    issuer = data.get('issuer')
    if not isinstance(issuer, list) or not issuer:
        raise ValueError('issuer 必须是非空列表')
    doc_type = data.get('doc_type')
    if not doc_type:
        raise ValueError('doc_type 必填')

    fields: dict[str, list[re.Pattern[str]]] = {}
    for name, value in (data.get('fields') or {}).items():
        candidates = value if isinstance(value, list) else [value]
        compiled = [re.compile(str(c)) for c in candidates if str(c).strip()]
        if compiled:
            fields[str(name)] = compiled

    return TemplateMatch(
        name=os.path.splitext(os.path.basename(path))[0],
        doc_type=str(doc_type),
        issuer=tuple(str(kw) for kw in issuer),
        fields=fields,
        exclude_keywords=tuple(
            str(kw) for kw in (data.get('exclude_keywords') or [])
        ),
    )


def match_template(
    text: str | None, dir_path: str | None = None
) -> TemplateMatch | None:
    """按文件名序稳定匹配文本，返回首个命中的模板；未命中返回 None

    命中条件：issuer 全部关键词命中，且 exclude_keywords 无一命中。
    """
    if not text:
        return None
    for template in load_templates(dir_path):
        if all(kw in text for kw in template.issuer) and not any(
            kw in text for kw in template.exclude_keywords
        ):
            return template
    return None


def extract_fields(
    text: str | None, template: TemplateMatch
) -> dict[str, str | None]:
    """按模板字段正则抽取文本，返回 字段名 → 原始字符串（未命中为 None）

    多候选 regex 时取第一个成功捕获组（第一个非空 group，无捕获组则整段匹配）。
    金额/日期不做格式转换——保持字符串，由调用方决定。
    """
    result: dict[str, str | None] = {}
    if not text:
        return {name: None for name in template.fields}
    for name, patterns in template.fields.items():
        captured: str | None = None
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                captured = next(
                    (g for g in m.groups() if g is not None), m.group(0)
                )
                break
        result[name] = captured
    return result


def _clear_cache_for_tests() -> None:
    """测试专用：清空模板缓存（不对外暴露）"""
    with _LOCK:
        _CACHE.clear()
