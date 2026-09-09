"""Đọc nội dung text — thứ thay thế cho OCR."""

from __future__ import annotations

from typing import Any

from . import uia
from .uia import UIA


def read_text(element: Any, max_chars: int = 8000) -> str:
    """Lấy nội dung văn bản của một phần tử.

    ``TextPattern`` trả về đúng ký tự mà ứng dụng đang giữ, nên dấu tiếng Việt, ký tự
    đặc biệt và ngắt dòng đều chính xác — khác hẳn OCR trên ảnh chụp.
    """
    attempts: list[str] = []

    pattern = uia.pattern(element, UIA.UIA_TextPatternId, UIA.IUIAutomationTextPattern)
    if pattern:
        try:
            text = pattern.DocumentRange.GetText(max_chars)
            if text:
                return _annotate(text, max_chars, "TextPattern")
            attempts.append("TextPattern: rỗng")
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"TextPattern: {exc}")

    value_pattern = uia.pattern(element, UIA.UIA_ValuePatternId, UIA.IUIAutomationValuePattern)
    if value_pattern:
        try:
            value = value_pattern.CurrentValue
            if value:
                return _annotate(value[:max_chars], max_chars, "ValuePattern")
            attempts.append("ValuePattern: rỗng")
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"ValuePattern: {exc}")

    name = uia.cached(element, UIA.UIA_NamePropertyId) or ""
    if name:
        return _annotate(name[:max_chars], max_chars, "Name property")

    return "(không có nội dung text) — đã thử: " + "; ".join(attempts or ["không có pattern nào"])


def _annotate(text: str, max_chars: int, source: str) -> str:
    truncated = "\n… (bị cắt ở max_chars)" if len(text) >= max_chars else ""
    return f"[nguồn: {source}, {len(text)} ký tự]\n{text}{truncated}"


def _row_cells(grid: Any, row: int, columns: int) -> list[str]:
    cells = []
    for column in range(columns):
        try:
            cell = grid.GetItem(row, column)
            cells.append(" ".join(str(cell.CurrentName or "").split()))
        except Exception:
            cells.append("")
    return cells


def read_table(element: Any, start_row: int = 0, max_rows: int = 50) -> str:
    """Đọc một bảng/lưới qua ``GridPattern`` — không phải đọc pixel.

    ``start_row`` để phân trang: không có nó thì mọi lần gọi đều bắt đầu từ hàng 0 và
    không bao giờ với tới phần sau của bảng dài.
    """
    grid = uia.pattern(element, UIA.UIA_GridPatternId, UIA.IUIAutomationGridPattern)
    if not grid:
        return "(phần tử này không có GridPattern — dùng observe(filter='table') hoặc find(by='pattern', query='grid') để tìm đúng phần tử lưới)"

    rows, columns = grid.CurrentRowCount, grid.CurrentColumnCount
    if start_row < 0:
        start_row = 0
    if rows and start_row >= rows:
        return f"# lưới {rows}×{columns}\n(start_row={start_row} vượt quá số hàng {rows})"

    end_row = min(rows, start_row + max_rows)
    lines = [f"# lưới {rows}×{columns} — đọc hàng {start_row}–{end_row - 1}"]

    # Khi phân trang, vẫn kèm hàng 0: ở nhiều lưới (SAP) đó là hàng tiêu đề, thiếu nó thì
    # các hàng phía sau mất hết ngữ nghĩa cột.
    if start_row > 0:
        lines.append("[hàng 0] " + "|".join(_row_cells(grid, 0, columns)))

    empty = 0
    for row in range(start_row, end_row):
        cells = _row_cells(grid, row, columns)
        if not any(cells):
            empty += 1
        lines.append("|".join(cells))

    read = end_row - start_row
    if empty:
        # Đừng lặng lẽ bỏ hàng rỗng: chính chúng là bằng chứng lưới bị ảo hoá.
        lines.append(
            f"({empty}/{read} hàng đọc được là rỗng — lưới ảo hoá, chỉ vùng đang render mới "
            f"có dữ liệu. RowCount={rows} là số logic, không phải số hàng thật đang có.)"
        )
    if rows > end_row:
        lines.append(
            f"… còn {rows - end_row} hàng nữa. Đọc tiếp bằng start_row={end_row} "
            f"(có thể phải cuộn lưới trước nếu phần đó chưa render)."
        )
    return "\n".join(lines)
