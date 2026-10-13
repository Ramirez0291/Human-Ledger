"""最小的 .xlsx 读取：第一张工作表 → 二维字符串表。

微信支付从 2024 年起导出的账单是 xlsx。只为读这种「一张表、纯值」的导出文件，
不值得引入 openpyxl：xlsx 就是 zip 里的几份 XML，标准库足够。

- 只读第一张工作表（按 workbook.xml 的顺序）
- 单元格一律转成字符串：共享字符串 / 内联字符串原样，数字保留原始文本
  （日期是 Excel 序列号，如 46268.48，由调用方按列含义换算，见 `excel_serial_to_datetime`）
- 空行跳过，行内缺的单元格补空串，与 csv_source.read_rows 的输出一致

上传文件不可信：解压前检查每个成员的声明大小，防 zip 炸弹；
XML 用标准库 expat 解析，Python 3.11 自带的 expat 已限制实体展开。
"""

from __future__ import annotations

import datetime as dt
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

MAX_MEMBER_BYTES = 50 * 1024 * 1024


class XlsxError(ValueError):
    pass


def is_xlsx(content: bytes) -> bool:
    return content[:4] == b"PK\x03\x04"


def _read(z: zipfile.ZipFile, name: str) -> bytes:
    info = z.getinfo(name)
    if info.file_size > MAX_MEMBER_BYTES:
        raise XlsxError("xlsx_member_too_large")
    return z.read(name)


def _first_sheet_path(z: zipfile.ZipFile) -> str:
    names = set(z.namelist())
    try:
        wb = ET.fromstring(_read(z, "xl/workbook.xml"))
        rels = ET.fromstring(_read(z, "xl/_rels/workbook.xml.rels"))
        sheet = wb.find(f"{_NS}sheets/{_NS}sheet")
        rid = sheet.get(f"{_REL_NS}id") if sheet is not None else None
        for rel in rels.iter(f"{_PKG_REL_NS}Relationship"):
            if rel.get("Id") == rid:
                target = rel.get("Target", "")
                path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(f"xl/{target}")
                if path in names:
                    return path
    except (KeyError, ET.ParseError):
        pass
    sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    if not sheets:
        raise XlsxError("xlsx_no_sheet")
    return sheets[0]


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return -1
    n = 0
    for ch in letters.group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _text(el: ET.Element) -> str:
    """<si> / <is> 里可能是一个 <t>，也可能是多段富文本 <r><t>…</t></r>。"""
    return "".join(t.text or "" for t in el.iter(f"{_NS}t"))


def read_xlsx_rows(content: bytes) -> list[list[str]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise XlsxError("xlsx_invalid") from exc

    with z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(_read(z, "xl/sharedStrings.xml"))
            shared = [_text(si) for si in root.iter(f"{_NS}si")]

        sheet = ET.fromstring(_read(z, _first_sheet_path(z)))

    rows: list[list[str]] = []
    for r in sheet.iter(f"{_NS}row"):
        cells: dict[int, str] = {}
        next_col = 0
        for c in r.iter(f"{_NS}c"):
            idx = _col_index(c.get("r", ""))
            if idx < 0:
                idx = next_col
            next_col = idx + 1
            kind = c.get("t")
            v = c.find(f"{_NS}v")
            if kind == "s":
                try:
                    val = shared[int(v.text)] if v is not None and v.text else ""
                except (ValueError, IndexError):
                    val = ""
            elif kind == "inlineStr":
                is_ = c.find(f"{_NS}is")
                val = _text(is_) if is_ is not None else ""
            else:
                val = v.text if v is not None and v.text is not None else ""
            cells[idx] = val.strip()
        if not cells or not any(cells.values()):
            continue
        width = max(cells) + 1
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


_EXCEL_EPOCH = dt.datetime(1899, 12, 30)


def excel_serial_to_datetime(text: str) -> dt.datetime | None:
    """Excel 序列号（1900 日期系统）→ datetime，精确到秒。不是数字返回 None。"""
    try:
        serial = float(text)
    except (TypeError, ValueError):
        return None
    if not 1 <= serial < 2958466:  # 9999-12-31
        return None
    seconds = round(serial * 86400)
    return _EXCEL_EPOCH + dt.timedelta(seconds=seconds)
