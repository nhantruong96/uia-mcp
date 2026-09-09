"""Chụp màn hình — lối thoát CUỐI CÙNG, không phải công cụ mặc định.

Cả dự án này tồn tại vì đọc cây trợ năng tốt hơn nhìn ảnh: nó cho biết trạng thái thật
(enabled, on/off, giá trị ô nhập), không tốn ~1.500 token mỗi lần nhìn, và không có lớp
lỗi "đoán sai toạ độ". Ảnh chụp không có thứ nào trong đó.

Nhưng có những bề mặt UIA thực sự mù — nội dung vẽ trên canvas: viewport 3D của Revit,
canvas AutoCAD, lưới Excel Online, game. Ở đó không còn gì để đọc, và một tấm ảnh là
phương án duy nhất còn lại.

Thứ tự bắt buộc:  API của ứng dụng  →  UIA  →  ảnh chụp.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

user32 = ctypes.WinDLL("user32", use_last_error=True)

OUT_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "uia-mcp" / "screenshots"

#: Số ảnh giữ lại; cũ hơn thì xoá để thư mục không phình ra vô hạn.
KEEP = 20

#: Độ dài tối thiểu của lời khai "đã thử gì" — đủ để không khai cho có.
MIN_JUSTIFICATION = 25


class NotLastResort(RuntimeError):
    """Gọi chụp màn hình mà chưa nêu được đã thử những gì trước đó."""


def _prune() -> None:
    try:
        files = sorted(OUT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[KEEP:]:
            stale.unlink(missing_ok=True)
    except Exception:
        pass


def capture(window_element: Any | None, tried: str) -> str:
    """Chụp một cửa sổ (hoặc toàn màn hình nếu ``window_element`` là None).

    ``tried`` là lời khai bắt buộc về những cách đã thử trước khi rơi xuống ảnh chụp.
    Nó không phải thủ tục hành chính: nó buộc người gọi dừng lại một nhịp để tự hỏi đã
    thử API của ứng dụng và đọc cây UIA chưa, và nó để lại dấu vết kiểm chứng được về
    việc *vì sao* lần này phải dùng tới ảnh.
    """
    if not tried or len(tried.strip()) < MIN_JUSTIFICATION:
        raise NotLastResort(
            "Ảnh chụp là lựa chọn cuối cùng. Hãy nêu cụ thể trong tham số `tried` những gì "
            "đã thử và thất bại — MCP riêng của ứng dụng (revit-mcp, Excel-MCP, Navisworks…), "
            "rồi observe()/find()/read_text() của UIA. Nếu chưa thử thì thử trước đã: chúng "
            "cho biết trạng thái thật và rẻ hơn ảnh hàng nghìn token."
        )

    from PIL import ImageGrab  # nhập muộn: chỉ trả giá khi thực sự chụp

    box = None
    label = "toàn màn hình"
    if window_element is not None:
        try:
            handle = int(window_element.CurrentNativeWindowHandle or 0)
        except Exception:
            handle = 0
        if handle and user32.IsWindow(handle):
            rect = wintypes.RECT()
            if user32.GetWindowRect(handle, ctypes.byref(rect)):
                box = (rect.left, rect.top, rect.right, rect.bottom)
                label = f"cửa sổ hwnd={handle}"
            if user32.IsIconic(handle):
                raise NotLastResort(
                    f"Cửa sổ hwnd={handle} đang minimize — ảnh chụp sẽ không có nội dung. "
                    f"Gọi act(<id Window>, 'restore') trước."
                )

    image = ImageGrab.grab(bbox=box, all_screens=box is None)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.png"
    image.save(path, "PNG")
    _prune()

    return (
        f"đã chụp {label}: {image.width}×{image.height}\n"
        f"{path}\n"
        f"Dùng tool Read trên đường dẫn trên để xem ảnh.\n"
        f"(đã thử trước đó: {tried.strip()})"
    )
