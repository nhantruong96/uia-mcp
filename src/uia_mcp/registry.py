"""Bảng ID ổn định: thứ thay thế cho toạ độ pixel.

Model chỉ nhìn thấy số nguyên nhỏ. Cùng một control phải giữ nguyên ID giữa hai lần
``observe``, nếu không model sẽ hành động lên phần tử sai sau mỗi lần quan sát lại.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from . import uia
from .uia import UIA

#: Số phần tử giữ lại. Vượt quá thì loại phần tử cũ nhất (LRU).
MAX_ENTRIES = 4000


def _identity_key(element: Any) -> tuple:
    """Khoá định danh bền nhất có thể lấy được từ một phần tử.

    ``RuntimeId`` do chính UIA sinh ra và ổn định suốt vòng đời của control.
    Khi không có, ta lùi về ``AutomationId`` (do lập trình viên app đặt, không đổi
    theo ngôn ngữ giao diện), rồi cuối cùng mới đến tên hiển thị.
    """
    rid = uia.runtime_id(element)
    if rid:
        return ("rt", rid)

    handle = uia.cached(element, UIA.UIA_NativeWindowHandlePropertyId, 0)
    pid = uia.cached(element, UIA.UIA_ProcessIdPropertyId, 0)
    automation_id = uia.cached(element, UIA.UIA_AutomationIdPropertyId, "")
    if automation_id:
        return ("aid", pid, handle, automation_id)

    return (
        "nm",
        pid,
        handle,
        uia.cached(element, UIA.UIA_ControlTypePropertyId, 0),
        uia.cached(element, UIA.UIA_NamePropertyId, ""),
        uia.rect(element),
    )


class ElementRegistry:
    """Ánh xạ hai chiều giữa ID ngắn và ``IUIAutomationElement``."""

    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._max = max_entries
        self._id_by_key: OrderedDict[tuple, int] = OrderedDict()
        self._element_by_id: dict[int, Any] = {}
        self._next_id = 0

    def register(self, element: Any) -> int:
        key = _identity_key(element)
        existing = self._id_by_key.get(key)
        if existing is not None:
            self._id_by_key.move_to_end(key)
            # Luôn thay bằng tham chiếu mới nhất: tham chiếu cũ có thể đã chết.
            self._element_by_id[existing] = element
            return existing

        element_id = self._next_id
        self._next_id += 1
        self._id_by_key[key] = element_id
        self._element_by_id[element_id] = element
        self._evict()
        return element_id

    def get(self, element_id: int) -> Any:
        element = self._element_by_id.get(element_id)
        if element is None:
            raise KeyError(
                f"id {element_id} không có trong bảng. Gọi observe() trước, hoặc phần tử "
                f"đã bị loại khỏi bộ nhớ."
            )
        return element

    def _evict(self) -> None:
        while len(self._id_by_key) > self._max:
            _, stale_id = self._id_by_key.popitem(last=False)
            self._element_by_id.pop(stale_id, None)


#: Bảng dùng chung cho cả tiến trình.
REGISTRY = ElementRegistry()
