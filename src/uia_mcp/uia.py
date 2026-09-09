"""Lớp bọc mỏng quanh COM client của Windows UI Automation.

Mọi hàm ở đây PHẢI được gọi từ thread STA (xem :mod:`uia_mcp.sta`).
"""

from __future__ import annotations

from typing import Any, Iterable

import os

import comtypes
import comtypes.client

comtypes.client.GetModule("UIAutomationCore.dll")
from comtypes.gen import UIAutomationClient as UIA  # noqa: E402

#: CUIAutomation8 — cho ta IUIAutomation2+ với các thuộc tính timeout và AutoSetFocus.
CLSID_CUIAutomation8 = "{E22AD333-B25F-460C-83D0-0581107395C9}"

#: Thời gian chờ provider trả lời một transaction.
#:
#: Đặt 5 s là quá ngắn cho ứng dụng nặng: Revit 2027 cần 6–16 s cho một lần duyệt subtree,
#: nên mọi truy vấn đều hỏng với ``UIA_E_TIMEOUT`` (0x80131505) — mà lỗi đó hiện ra dưới
#: dạng COMError khó hiểu, dễ tưởng nhầm là app treo. 30 s bao được Revit, và thread STA
#: vẫn còn watchdog riêng của nó nên không có nguy cơ treo vô hạn.
TRANSACTION_TIMEOUT_MS = int(os.environ.get("UIA_MCP_TRANSACTION_TIMEOUT_MS", "30000"))
CONNECTION_TIMEOUT_MS = int(os.environ.get("UIA_MCP_CONNECTION_TIMEOUT_MS", "5000"))

CONTROL_TYPE_NAMES: dict[int, str] = {
    value: key[len("UIA_") : -len("ControlTypeId")]
    for key, value in vars(UIA).items()
    if key.startswith("UIA_") and key.endswith("ControlTypeId")
}

# --- Thuộc tính nạp sẵn trong MỘT round-trip COM ---------------------------------
# Mỗi property ở đây là công việc provider phải làm, nên chỉ giữ những gì thực sự
# đổi được quyết định của agent.

IDENTITY_PROPS = (
    UIA.UIA_NamePropertyId,
    UIA.UIA_ControlTypePropertyId,
    UIA.UIA_LocalizedControlTypePropertyId,
    UIA.UIA_AutomationIdPropertyId,
    UIA.UIA_ClassNamePropertyId,
    UIA.UIA_RuntimeIdPropertyId,
    UIA.UIA_BoundingRectanglePropertyId,
    UIA.UIA_ProcessIdPropertyId,
    UIA.UIA_NativeWindowHandlePropertyId,
    UIA.UIA_HelpTextPropertyId,
    UIA.UIA_AcceleratorKeyPropertyId,
)

STATE_PROPS = (
    UIA.UIA_IsEnabledPropertyId,
    UIA.UIA_IsOffscreenPropertyId,
    UIA.UIA_HasKeyboardFocusPropertyId,
    UIA.UIA_IsKeyboardFocusablePropertyId,
    UIA.UIA_IsPasswordPropertyId,
    UIA.UIA_ValueValuePropertyId,
    UIA.UIA_ValueIsReadOnlyPropertyId,
    UIA.UIA_ToggleToggleStatePropertyId,
    UIA.UIA_SelectionItemIsSelectedPropertyId,
    UIA.UIA_ExpandCollapseExpandCollapseStatePropertyId,
    UIA.UIA_RangeValueValuePropertyId,
    UIA.UIA_ScrollVerticallyScrollablePropertyId,
    UIA.UIA_ScrollVerticalScrollPercentPropertyId,
    UIA.UIA_ScrollHorizontallyScrollablePropertyId,
    UIA.UIA_ScrollHorizontalScrollPercentPropertyId,
)

#: (property id "pattern có sẵn không", nhãn ngắn hiển thị cho model)
PATTERN_FLAGS: tuple[tuple[int, str], ...] = (
    (UIA.UIA_IsInvokePatternAvailablePropertyId, "invoke"),
    (UIA.UIA_IsValuePatternAvailablePropertyId, "value"),
    (UIA.UIA_IsTogglePatternAvailablePropertyId, "toggle"),
    (UIA.UIA_IsSelectionItemPatternAvailablePropertyId, "select"),
    (UIA.UIA_IsExpandCollapsePatternAvailablePropertyId, "expand"),
    (UIA.UIA_IsScrollPatternAvailablePropertyId, "scroll"),
    (UIA.UIA_IsTextPatternAvailablePropertyId, "text"),
    (UIA.UIA_IsGridPatternAvailablePropertyId, "grid"),
    (UIA.UIA_IsRangeValuePatternAvailablePropertyId, "range"),
    (UIA.UIA_IsWindowPatternAvailablePropertyId, "window"),
)

#: Cache thêm nhưng KHÔNG hiển thị: hai pattern này có mặt trên gần như mọi phần tử nên
#: in ra chỉ tốn token mà không phân biệt được gì. Thang fallback vẫn dùng chúng.
SILENT_PATTERN_FLAGS = (
    UIA.UIA_IsScrollItemPatternAvailablePropertyId,
    UIA.UIA_IsLegacyIAccessiblePatternAvailablePropertyId,
)

ALL_PROPS = (
    IDENTITY_PROPS + STATE_PROPS + tuple(pid for pid, _ in PATTERN_FLAGS) + SILENT_PATTERN_FLAGS
)

#: Nhãn pattern → property id, để tìm theo pattern ("grid", "scroll", "invoke"…).
PATTERN_BY_LABEL: dict[str, int] = {label: pid for pid, label in PATTERN_FLAGS}
PATTERN_BY_LABEL["scrollinto"] = UIA.UIA_IsScrollItemPatternAvailablePropertyId
PATTERN_BY_LABEL["legacy"] = UIA.UIA_IsLegacyIAccessiblePatternAvailablePropertyId

#: Tên control type (viết thường) → id, để tìm theo loại ("tabitem", "document"…).
CONTROL_TYPE_IDS: dict[str, int] = {
    name.casefold(): type_id for type_id, name in CONTROL_TYPE_NAMES.items()
}

#: Các pattern khiến một control đáng để agent nhìn thấy.
ACTIONABLE_FLAGS = (
    UIA.UIA_IsInvokePatternAvailablePropertyId,
    UIA.UIA_IsValuePatternAvailablePropertyId,
    UIA.UIA_IsTogglePatternAvailablePropertyId,
    UIA.UIA_IsSelectionItemPatternAvailablePropertyId,
    UIA.UIA_IsExpandCollapsePatternAvailablePropertyId,
    UIA.UIA_IsRangeValuePatternAvailablePropertyId,
)

_automation: Any = None


def automation() -> Any:
    """IUIAutomation dùng chung. Chỉ tạo một lần, trên thread STA."""
    global _automation
    if _automation is None:
        obj = comtypes.client.CreateObject(CLSID_CUIAutomation8, interface=UIA.IUIAutomation)
        try:
            obj2 = obj.QueryInterface(UIA.IUIAutomation2)
            # Không bao giờ tự cướp focus của người dùng khi chỉ đang quan sát.
            obj2.AutoSetFocus = False
            obj2.ConnectionTimeout = CONNECTION_TIMEOUT_MS
            obj2.TransactionTimeout = TRANSACTION_TIMEOUT_MS
            obj = obj2
        except Exception:
            pass  # IUIAutomation2 không có trên bản Windows quá cũ — vẫn chạy được
        _automation = obj
    return _automation


# --- Điều kiện lọc (chạy TRONG tiến trình ứng dụng đích) -------------------------


def cond_true() -> Any:
    return automation().CreateTrueCondition()


def cond_prop(property_id: int, value: Any) -> Any:
    return automation().CreatePropertyCondition(property_id, value)


def cond_or(*conditions: Any) -> Any:
    uia = automation()
    result = conditions[0]
    for cond in conditions[1:]:
        result = uia.CreateOrCondition(result, cond)
    return result


def cond_and(*conditions: Any) -> Any:
    uia = automation()
    result = conditions[0]
    for cond in conditions[1:]:
        result = uia.CreateAndCondition(result, cond)
    return result


def cond_onscreen() -> Any:
    return cond_prop(UIA.UIA_IsOffscreenPropertyId, False)


def cond_interactive() -> Any:
    """Có ít nhất một pattern hành động được, và đang hiển thị.

    Cố tình *không* lọc theo ``IsEnabled``: biết một nút đang bị disable là thông tin
    có giá trị — đó chính là thứ ảnh chụp màn hình không nói được chắc chắn.
    """
    return cond_and(cond_or(*(cond_prop(pid, True) for pid in ACTIONABLE_FLAGS)), cond_onscreen())


def cond_text() -> Any:
    return cond_and(
        cond_or(
            cond_prop(UIA.UIA_IsTextPatternAvailablePropertyId, True),
            cond_prop(UIA.UIA_ControlTypePropertyId, UIA.UIA_TextControlTypeId),
            cond_prop(UIA.UIA_ControlTypePropertyId, UIA.UIA_DocumentControlTypeId),
        ),
        cond_onscreen(),
    )


def cond_table() -> Any:
    """Chỉ các phần tử là lưới/bảng.

    Không có filter này thì ``read_table`` gần như vô dụng ngoài đời: bảng thật nằm sâu
    trong cây (Outlook: phần tử thứ 196/325) nên rơi ra ngoài ``max_elements``, và nó
    không có pattern hành động nào nên ``interactive`` cũng loại nó.
    """
    return cond_and(
        cond_or(
            cond_prop(UIA.UIA_IsGridPatternAvailablePropertyId, True),
            cond_prop(UIA.UIA_IsTablePatternAvailablePropertyId, True),
        ),
        cond_onscreen(),
    )


FILTERS = {
    "interactive": cond_interactive,
    "text": cond_text,
    "table": cond_table,
    "all": cond_onscreen,
}


# --- Cache --------------------------------------------------------------------


def cache_request(props: Iterable[int] = ALL_PROPS) -> Any:
    """CacheRequest cho ``FindAllBuildCache``.

    ``TreeScope`` PHẢI là ``Element``. Nếu để kèm ``Children``/``Subtree``, provider sẽ
    dựng cache cho subtree của *từng* phần tử trả về — công việc bùng nổ bậc hai, đo
    được là chậm hơn 2–6× so với đọc live (xem research/§3.1.1).

    ``AutomationElementMode_Full`` là bắt buộc ở đây: chế độ ``None`` nhanh hơn ~12%
    nhưng phần tử trả về không giữ tham chiếu COM nào, nên không thể hành động lên nó.
    """
    request = automation().CreateCacheRequest()
    request.TreeScope = UIA.TreeScope_Element
    request.AutomationElementMode = UIA.AutomationElementMode_Full
    for prop in props:
        request.AddProperty(prop)
    return request


# --- Đọc property an toàn ------------------------------------------------------

_SIMPLE = (bool, int, float, str)


def cached(element: Any, property_id: int, default: Any = None) -> Any:
    """Đọc một property đã cache.

    UIA trả về một sentinel COM "không hỗ trợ" cho property mà provider không có; ta
    quy mọi thứ không phải kiểu đơn giản về ``default``.
    """
    try:
        value = element.GetCachedPropertyValue(property_id)
    except Exception:
        return default
    return value if isinstance(value, _SIMPLE) else default


def runtime_id(element: Any) -> tuple[int, ...] | None:
    try:
        value = element.GetCachedPropertyValue(UIA.UIA_RuntimeIdPropertyId)
    except Exception:
        return None
    try:
        return tuple(int(part) for part in value)
    except Exception:
        return None


def rect(element: Any, live: bool = False) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom), hoặc None nếu không có hình học.

    ``live=True`` bỏ qua cache và hỏi lại provider. Bắt buộc dùng khi sắp bơm chuột:
    rect trong cache là ảnh chụp lúc ``observe``, có thể đã cũ hàng giây, và phần tử đã
    dịch đi (cuộn, đổi layout). Click theo toạ độ cũ chính là lỗi "click trượt".
    """
    box = None
    if not live:
        try:
            box = element.CachedBoundingRectangle
        except Exception:
            box = None
    if box is None:
        try:
            box = element.CurrentBoundingRectangle
        except Exception:
            return None
    try:
        left, top, right, bottom = int(box.left), int(box.top), int(box.right), int(box.bottom)
    except Exception:
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def center(element: Any, live: bool = False) -> tuple[int, int] | None:
    box = rect(element, live=live)
    if box is None:
        return None
    left, top, right, bottom = box
    return (left + right) // 2, (top + bottom) // 2


def pattern(element: Any, pattern_id: int, interface: Any) -> Any:
    """Lấy một control pattern, hoặc None nếu provider không hỗ trợ."""
    try:
        raw = element.GetCurrentPattern(pattern_id)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return raw.QueryInterface(interface)
    except Exception:
        return None


def control_type_name(element: Any) -> str:
    type_id = cached(element, UIA.UIA_ControlTypePropertyId)
    if type_id is None:
        return "Unknown"
    return CONTROL_TYPE_NAMES.get(type_id, str(type_id))
