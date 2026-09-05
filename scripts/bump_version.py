"""递增并同步项目的发布版本号。"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILE = ROOT / 'backend' / 'invoice_processor' / 'version.py'
PYPROJECT_FILE = ROOT / 'pyproject.toml'
WEB_PACKAGE_FILE = ROOT / 'web' / 'package.json'
WEB_LOCK_FILE = ROOT / 'web' / 'package-lock.json'
VERSION_INFO_FILE = ROOT / 'version_info.txt'
VERSION_PATTERN = re.compile(r"(?m)^__version__ = '(\d+\.\d+\.\d+)'$")
Replacement = str | Callable[[re.Match[str]], str]


def read_version() -> str:
    match = VERSION_PATTERN.search(SOURCE_FILE.read_text(encoding='utf-8'))
    if not match:
        raise RuntimeError(f'无法读取版本号: {SOURCE_FILE}')
    return match.group(1)


def bump(version: str, level: str) -> str:
    major, minor, patch = (int(part) for part in version.split('.'))
    if level == 'major':
        return f'{major + 1}.0.0'
    if level == 'minor':
        return f'{major}.{minor + 1}.0'
    return f'{major}.{minor}.{patch + 1}'


def replace_once(path: Path, replacements: list[tuple[str, Replacement]]) -> None:
    content = path.read_text(encoding='utf-8')
    for pattern, replacement in replacements:
        content, count = re.subn(pattern, replacement, content, count=1)
        if count != 1:
            raise RuntimeError(f'版本字段未找到或不唯一: {path} / {pattern}')
    path.write_text(content, encoding='utf-8')


def update_files(version: str) -> None:
    windows_version = f'{version}.0'
    version_parts = ', '.join((*version.split('.'), '0'))
    release_year = date.today().year
    replace_once(
        SOURCE_FILE,
        [(r"(?m)^__version__ = '\d+\.\d+\.\d+'$", f"__version__ = '{version}'")],
    )
    replace_once(
        PYPROJECT_FILE,
        [(r'(?m)^(version\s*=\s*)"[^"]+"', rf'\g<1>"{version}"')],
    )
    replace_once(
        WEB_PACKAGE_FILE,
        [(r'(?m)^(\s*"version":\s*)"[^"]+"', rf'\g<1>"{version}"')],
    )
    replace_once(
        WEB_LOCK_FILE,
        [
            (
                r'(\A\{\s*"name":\s*"[^"]+",\s*"version":\s*)"[^"]+"',
                rf'\g<1>"{version}"',
            ),
            (
                r'("packages":\s*\{\s*"":\s*\{\s*"name":\s*"[^"]+",\s*"version":\s*)"[^"]+"',
                rf'\g<1>"{version}"',
            ),
        ],
    )
    replace_once(
        VERSION_INFO_FILE,
        [
            (r'filevers=\(\d+(?:,\s*\d+){3}\)', f'filevers=({version_parts})'),
            (r'prodvers=\(\d+(?:,\s*\d+){3}\)', f'prodvers=({version_parts})'),
            (
                r"StringStruct\(u'FileVersion', u'[^']+'\)",
                f"StringStruct(u'FileVersion', u'{windows_version}')",
            ),
            (
                r"StringStruct\(u'ProductVersion', u'[^']+'\)",
                f"StringStruct(u'ProductVersion', u'{windows_version}')",
            ),
            (
                r"StringStruct\(u'LegalCopyright', u'Copyright \\xa9 SYNTEC \d{4}'\)",
                lambda match: (
                    f"StringStruct(u'LegalCopyright', u'Copyright \\xa9 SYNTEC "
                    f"{release_year}')"
                ),
            ),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'level', nargs='?', choices=('patch', 'minor', 'major'), default='patch',
        help='递增级别，默认 patch',
    )
    parser.add_argument(
        '--check', action='store_true', help='只显示当前版本，不修改文件',
    )
    args = parser.parse_args()
    current = read_version()
    if args.check:
        print(current)
        return
    next_version = bump(current, args.level)
    update_files(next_version)
    print(f'{current} -> {next_version}')


if __name__ == '__main__':
    main()
