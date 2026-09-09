"""Quan sát: biến cây UIA thành bảng text nén cho model.

Không có pixel nào được đọc ở đây.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Any

from . import uia
from .registry import REGISTRY
from .uia import UIA

user32 = ctypes.WinDLL("user32", use_last_error=True)

TOGGLE_STATES = {0: "off", 1: "on", 2: "indeterminate"}
EXPAND_STATES = {0: "collapsed", 1: "expanded", 2: "partially-expanded"}

MAX_NAME = 90
MAX_VALUE = 70


def _clean(text: Any, limit: int) -> str:
    """Một ô trong bảng: không xuống dòng, không ký tự phân cách, có giới hạn độ dài."""
    if not text:
        return ""
    flat = " ".join(str(text).split()).replace("|", "/")
    return flat[: limit - 1] + "…" if len(flat) > limit else flat


# --- Chọn cửa sổ ---------------------------------------------------------------


def _top_level_windows(max_attempts: int = 3) -> list[Any]:
    """Chụp danh sách cửa sổ top-level bằng TreeWalker.

    Danh sách này thay đổi liên tục: tooltip, menu popup, cửa sổ đang đóng. Nếu một
    sibling chết đúng lúc đang duyệt thì ``GetNextSiblingElement`` ném COMError và cả
    lần duyệt hỏng theo — nên phải bọc lại, giữ phần đã lấy được, và thử lại.
    """
    for attempt in range(max_attempts):
        automation = uia.automation()
        walker = automation.ControlViewWalker
        windows: list[Any] = []
        try:
            child = walker.GetFirstChildElement(automation.GetRootElement())
            while child:
                windows.append(child)
                child = walker.GetNextSiblingElement(child)
            return windows
        except Exception:
            if windows:
                return windows  # danh sách thiếu vẫn hơn là hỏng cả lời gọi
            time.sleep(0.1 * (attempt + 1))
    return []


def list_windows() -> str:
    foreground = user32.GetForegroundWindow()
    rows = ["# hwnd|class|pid|title|state"]
    for window in _top_level_windows():
        try:
            handle = window.CurrentNativeWindowHandle or 0
            rows.append(
                "|".join(
                    [
                        str(handle),
                        _clean(window.CurrentClassName, 40),
                        str(window.CurrentProcessId),
                        _clean(window.CurrentName, MAX_NAME),
                        "focused" if handle == foreground else "",
                    ]
                )
            )
        except Exception:
            continue
    return "\n".join(rows)


def resolve_window(spec: str) -> Any:
    """``"focused"`` | ``"desktop"`` | hwnd dạng số | một phần tiêu đề cửa sổ."""
    automation = uia.automation()
    spec = (spec or "focused").strip()

    if spec == "desktop":
        return automation.GetRootElement()

    if spec == "focused":
        handle = user32.GetForegroundWindow()
        if not handle:
            raise ValueError("không có cửa sổ nào đang ở foreground")
        return automation.ElementFromHandle(handle)

    if spec.lstrip("-").isdigit():
        handle = int(spec)
        if not user32.IsWindow(handle):
            raise ValueError(
                f"hwnd {handle} không còn tồn tại — cửa sổ đã đóng. Gọi list_windows() "
                f"để lấy hwnd hiện tại."
            )
        try:
            element = automation.ElementFromHandle(handle)
        except Exception as exc:  # COMError khi cửa sổ chết ngay giữa lời gọi
            raise ValueError(f"hwnd {handle} không đọc được qua UIA: {exc}") from None
        if not element:
            raise ValueError(f"hwnd {handle} không có provider UIA")
        return element

    needle = spec.casefold()
    for window in _top_level_windows():
        try:
            if needle in (window.CurrentName or "").casefold():
                return window
        except Exception:
            continue
    raise ValueError(f"không tìm thấy cửa sổ nào có tiêu đề chứa {spec!r}")


def window_visual_state(handle: int) -> str:
    """"minimized" | "maximized" | "normal" | "" (không phải hwnd hợp lệ)."""
    if not handle or not user32.IsWindow(handle):
        return ""
    if user32.IsIconic(handle):
        return "minimized"
    if user32.IsZoomed(handle):
        return "maximized"
    return "normal"


def _window_header(window: Any) -> str:
    try:
        name = _clean(window.CurrentName, MAX_NAME) or "(không tiêu đề)"
        class_name = window.CurrentClassName
        pid = window.CurrentProcessId
        handle = window.CurrentNativeWindowHandle or 0
    except Exception:
        return "window: (không đọc được)"
    state = window_visual_state(handle)
    suffix = f" state={state}" if state and state != "normal" else ""
    return f"window: {name!r} hwnd={handle} class={class_name} pid={pid}{suffix}"


# --- Mô tả một phần tử ---------------------------------------------------------


def _states(element: Any) -> str:
    """Trạng thái *thật* của phần tử.

    Mỗi property chỉ được đọc khi pattern tương ứng thực sự tồn tại. UIA trả về giá trị
    mặc định (ToggleState=indeterminate, RangeValue=0, IsReadOnly=True) cho mọi phần tử
    kể cả khi provider không hỗ trợ pattern đó — báo cáo nguyên xi sẽ dán nhãn sai lên
    gần như toàn bộ cây, và trạng thái sai còn tệ hơn không có trạng thái.
    """
    parts: list[str] = []
    has = lambda property_id: uia.cached(element, property_id) is True  # noqa: E731

    if has(UIA.UIA_HasKeyboardFocusPropertyId):
        parts.append("focused")
    if uia.cached(element, UIA.UIA_IsEnabledPropertyId) is False:
        parts.append("disabled")

    if has(UIA.UIA_IsTogglePatternAvailablePropertyId):
        toggle = uia.cached(element, UIA.UIA_ToggleToggleStatePropertyId)
        if toggle in TOGGLE_STATES:
            parts.append(TOGGLE_STATES[toggle])

    if has(UIA.UIA_IsSelectionItemPatternAvailablePropertyId) and has(
        UIA.UIA_SelectionItemIsSelectedPropertyId
    ):
        parts.append("selected")

    if has(UIA.UIA_IsExpandCollapsePatternAvailablePropertyId):
        expand = uia.cached(element, UIA.UIA_ExpandCollapseExpandCollapseStatePropertyId)
        if expand in EXPAND_STATES:
            parts.append(EXPAND_STATES[expand])

    if has(UIA.UIA_IsValuePatternAvailablePropertyId):
        if has(UIA.UIA_IsPasswordPropertyId):
            parts.append("value=***")
        else:
            value = uia.cached(element, UIA.UIA_ValueValuePropertyId)
            if value:
                parts.append(f"value={_clean(value, MAX_VALUE)!r}")
        if has(UIA.UIA_ValueIsReadOnlyPropertyId):
            parts.append("readonly")

    if has(UIA.UIA_IsRangeValuePatternAvailablePropertyId):
        number = uia.cached(element, UIA.UIA_RangeValueValuePropertyId)
        if isinstance(number, (int, float)):
            parts.append(f"number={number:g}")

    if has(UIA.UIA_IsScrollPatternAvailablePropertyId):
        if has(UIA.UIA_ScrollVerticallyScrollablePropertyId):
            percent = uia.cached(element, UIA.UIA_ScrollVerticalScrollPercentPropertyId)
            parts.append(
                f"scroll-v={percent:.0f}%" if isinstance(percent, (int, float)) else "scroll-v"
            )
        if has(UIA.UIA_ScrollHorizontallyScrollablePropertyId):
            parts.append("scroll-h")

    return ",".join(parts)


def _patterns(element: Any) -> str:
    return ",".join(
        label for property_id, label in uia.PATTERN_FLAGS if uia.cached(element, property_id) is True
    )


def describe(element: Any) -> str:
    """Một dòng bảng cho một phần tử, kèm ID đã đăng ký."""
    element_id = REGISTRY.register(element)
    name = _clean(uia.cached(element, UIA.UIA_NamePropertyId), MAX_NAME)
    if not name:
        name = _clean(uia.cached(element, UIA.UIA_AutomationIdPropertyId), MAX_NAME)
    if not name:
        # Không tên, không AutomationId: ít nhất cho ClassName để hai dòng rỗng còn phân
        # biệt được với nhau. Một dòng "4|Tab|||" thì không dùng vào việc gì.
        class_name = _clean(uia.cached(element, UIA.UIA_ClassNamePropertyId), MAX_NAME)
        if class_name:
            name = f".{class_name}"
    shortcut = uia.cached(element, UIA.UIA_AcceleratorKeyPropertyId)
    if shortcut:
        name = f"{name} [{_clean(shortcut, 20)}]" if name else f"[{_clean(shortcut, 20)}]"
    return "|".join(
        [str(element_id), uia.control_type_name(element), name, _states(element), _patterns(element)]
    )


# --- Điểm vào chính ------------------------------------------------------------


def observe(window: str = "focused", filter: str = "interactive", max_elements: int = 250) -> str:
    if filter not in uia.FILTERS:
        raise ValueError(f"filter phải là một trong {sorted(uia.FILTERS)}")

    root = resolve_window(window)
    condition = uia.FILTERS[filter]()
    request = uia.cache_request()
    found = root.FindAllBuildCache(UIA.TreeScope_Subtree, condition, request)

    total = found.Length
    rows = [_window_header(root)]

    # Cửa sổ minimize không render gì, nên cây nội dung của nó co lại chỉ còn khung.
    # Không nói ra thì agent sẽ kết luận nhầm là "ứng dụng này không có UI".
    try:
        handle = root.CurrentNativeWindowHandle or 0
    except Exception:
        handle = 0
    if window_visual_state(handle) == "minimized":
        rows.append(
            "CẢNH BÁO: cửa sổ đang minimize — Windows không render nội dung nên phần lớn "
            "cây UI không tồn tại lúc này. Gọi act(<id của Window>, 'restore') trước."
        )

    rows.append("# id|type|name|state|patterns")
    for index in range(min(total, max_elements)):
        try:
            rows.append(describe(found.GetElement(index)))
        except Exception:
            continue

    if total > max_elements:
        rows.append(
            f"… còn {total - max_elements} phần tử nữa bị cắt. Thu hẹp bằng window=<hwnd> "
            f"hoặc tăng max_elements."
        )
    if total == 0:
        rows.append(_empty_hint(root, filter))
    return "\n".join(rows)


#: Class name của các cửa sổ do Chromium vẽ (Chrome, Edge, Electron, VS Code…).
CHROMIUM_CLASSES = {"Chrome_WidgetWin_0", "Chrome_WidgetWin_1"}


def _web_content_exposed(window: Any) -> bool:
    """Cửa sổ Chromium này đã bật provider trợ năng cho nội dung web chưa?

    Dấu hiệu chính xác: có ``Document`` kèm ``TextPattern``. Khung trình duyệt (nút, thanh
    địa chỉ) luôn lộ ra dù accessibility tắt; chỉ nội dung trang mới sinh Document.
    """
    try:
        condition = uia.cond_and(
            uia.cond_prop(UIA.UIA_ControlTypePropertyId, UIA.UIA_DocumentControlTypeId),
            uia.cond_prop(UIA.UIA_IsTextPatternAvailablePropertyId, True),
        )
        return bool(window.FindFirst(UIA.TreeScope_Subtree, condition))
    except Exception:
        return False


def _empty_hint(window: Any, filter: str) -> str:
    """Giải thích *đúng* lý do cây rỗng.

    Gợi ý sai còn tệ hơn không gợi ý. Chỉ nhìn class cửa sổ là chưa đủ: một tab Excel
    Online trong Edge có cây trợ năng đầy đủ nhưng vẫn không có bảng nào, vì lưới được vẽ
    trên canvas. Đổ lỗi cho `--force-renderer-accessibility` lúc đó là đẩy agent đi sửa
    nhầm chỗ. Nên phải kiểm tra xem nội dung web *thực sự* có lộ ra không.
    """
    try:
        class_name = window.CurrentClassName
    except Exception:
        class_name = ""

    if class_name in CHROMIUM_CLASSES and not _web_content_exposed(window):
        return (
            "(không có phần tử nào — cửa sổ Chromium này chưa lộ nội dung web; thử khởi "
            "động trình duyệt với --force-renderer-accessibility)"
        )
    if filter != "all":
        extra = ""
        if class_name in CHROMIUM_CLASSES:
            extra = (
                " Cây trợ năng của trang vẫn lộ bình thường, nên đây là chuyện trang không có "
                "loại phần tử đó — nội dung vẽ trên canvas (lưới Excel Online, biểu đồ, game) "
                "không sinh ra control UIA."
            )
        return (
            f"(không có phần tử nào khớp filter={filter!r} — thử filter='all' để xem cửa sổ "
            f"này thực sự lộ ra những gì.{extra})"
        )
    return "(không có phần tử nào đang hiển thị trong cửa sổ này)"


# --- Tìm kiếm -----------------------------------------------------------------

#: Trường nào được so khớp cho mỗi kiểu tìm.
SEARCH_FIELDS = {
    "name": (UIA.UIA_NamePropertyId,),
    "class": (UIA.UIA_ClassNamePropertyId,),
    "automation_id": (UIA.UIA_AutomationIdPropertyId,),
    "auto": (
        UIA.UIA_NamePropertyId,
        UIA.UIA_AutomationIdPropertyId,
        UIA.UIA_ClassNamePropertyId,
    ),
}
SEARCH_MODES = set(SEARCH_FIELDS) | {"type", "pattern"}


def _match_rank(element: Any, needle: str, fields: tuple[int, ...]) -> int | None:
    """0 = khớp chính xác, 1 = khớp đầu chuỗi, 2 = chứa. None = không khớp."""
    best: int | None = None
    for property_id in fields:
        value = uia.cached(element, property_id)
        if not value:
            continue
        folded = str(value).casefold()
        if folded == needle:
            return 0
        if folded.startswith(needle):
            best = 1 if best is None else min(best, 1)
        elif needle in folded:
            best = 2 if best is None else min(best, 2)
    return best


def find(
    query: str,
    window: str = "focused",
    by: str = "auto",
    limit: int = 20,
    include_offscreen: bool = False,
    within: int | None = None,
) -> str:
    """Tìm phần tử ở bất kỳ độ sâu nào, không phụ thuộc ``max_elements`` của observe.

    ``observe`` cắt theo thứ tự duyệt cây, nên thứ nằm sâu thì không bao giờ tới lượt:
    bảng của Outlook là phần tử 196/325, và tab thật của Edge nằm dưới ``EdgeTabStrip``.
    Không có ``find`` thì những phần tử đó tồn tại nhưng không gọi tới được.

    ``within`` thu phạm vi về một nhánh con. Tìm trong cả cửa sổ trình duyệt sẽ lẫn toàn
    bộ chrome của Edge — nút, thanh địa chỉ, bookmark — vào kết quả của trang web.
    """
    by = (by or "auto").strip().lower()
    if by not in SEARCH_MODES:
        raise ValueError(f"by phải là một trong {sorted(SEARCH_MODES)}")
    needle = (query or "").strip()
    if not needle:
        raise ValueError("find cần query không rỗng")

    if within is not None:
        root = REGISTRY.get(within)
        scope = f"trong id={within} ({uia.control_type_name(root)} "
        scope += f"{_clean(uia.cached(root, UIA.UIA_NamePropertyId), 50)!r})"
    else:
        root = resolve_window(window)
        scope = _window_header(root)

    # Lọc ở phía provider bất cứ khi nào có thể — rẻ hơn nhiều so với lọc phía client.
    if by == "type":
        type_id = uia.CONTROL_TYPE_IDS.get(needle.casefold())
        if type_id is None:
            raise ValueError(
                f"không có control type {needle!r}. Ví dụ hợp lệ: Button, TabItem, Document, "
                f"Table, Edit, ListItem, MenuItem, TreeItem."
            )
        condition = uia.cond_prop(UIA.UIA_ControlTypePropertyId, type_id)
    elif by == "pattern":
        property_id = uia.PATTERN_BY_LABEL.get(needle.casefold())
        if property_id is None:
            raise ValueError(
                f"không có pattern {needle!r}. Hợp lệ: {sorted(uia.PATTERN_BY_LABEL)}"
            )
        condition = uia.cond_prop(property_id, True)
    else:
        condition = uia.cond_true()

    if not include_offscreen:
        condition = uia.cond_and(condition, uia.cond_onscreen())

    found = root.FindAllBuildCache(UIA.TreeScope_Subtree, condition, uia.cache_request())

    if by in ("type", "pattern"):
        # Điều kiện đã lọc đúng rồi; giữ nguyên thứ tự cây.
        matches = [(0, found.GetElement(i)) for i in range(found.Length)]
    else:
        folded = needle.casefold()
        fields = SEARCH_FIELDS[by]
        matches = []
        for index in range(found.Length):
            element = found.GetElement(index)
            rank = _match_rank(element, folded, fields)
            if rank is not None:
                matches.append((rank, element))
        # Khớp chính xác lên trước, rồi khớp đầu chuỗi, rồi mới đến chứa.
        matches.sort(key=lambda pair: pair[0])

    # Khớp chính xác đáng tin hơn hẳn khớp một phần: tìm class 'EdgeTab' cũng trúng
    # 'EdgeTabCloseButton', 'EdgeTabStrip'… Nói rõ có bao nhiêu cái chính xác để biết
    # tin mấy dòng đầu.
    exact = sum(1 for rank, _ in matches if rank == 0)
    note = f", {exact} khớp chính xác (xếp đầu)" if exact and exact < len(matches) else ""
    header = f"find({needle!r}, by={by}): {len(matches)} kết quả{note}"
    rows = [scope, header, "# id|type|name|state|patterns"]
    for _, element in matches[:limit]:
        try:
            rows.append(describe(element))
        except Exception:
            continue
    if len(matches) > limit:
        rows.append(f"… còn {len(matches) - limit} kết quả nữa. Tăng limit nếu cần.")
    if not matches:
        rows.append(
            "(không khớp gì — thử by='auto' để quét cả name/automation_id/class, "
            "include_offscreen=True cho phần tử đang ẩn, hoặc window='desktop' để tìm toàn máy)"
        )
    return "\n".join(rows)


def describe_at(x: int, y: int) -> str:
    """Phần tử nằm dưới một điểm màn hình. ~2ms, không chụp ảnh."""
    point = wintypes.POINT(int(x), int(y))
    element = uia.automation().ElementFromPoint(point)
    if not element:
        return f"({x},{y}): không có phần tử UIA nào"
    request = uia.cache_request()
    element = element.BuildUpdatedCache(request)
    return "\n".join([f"# id|type|name|state|patterns", describe(element)])
