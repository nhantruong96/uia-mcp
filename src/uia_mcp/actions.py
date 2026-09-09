"""Hành động: thang fallback từ control pattern xuống chuột thật.

Đây là phần mà phần lớn "UIA agent" bỏ lỡ — họ dùng UIA để *nhìn* nhưng vẫn *bấm*
bằng toạ độ. Bậc 1 không cần cửa sổ ở foreground, không cướp chuột của người dùng,
và không có lớp lỗi "click trượt".

Mỗi lần gọi đều báo lại nó đã dùng bậc nào. Đó là tín hiệu đo được về chất lượng
trợ năng của từng ứng dụng, và là dữ liệu để biết khi nào buộc phải dùng vision.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import rawinput, uia
from .uia import UIA

#: Chờ UI ổn định sau một hành động trước khi báo cáo lại.
SETTLE = 0.15

NO_SCROLL = getattr(UIA, "UIA_ScrollPatternNoScroll", -1.0)
SCROLL_LARGE_INCREMENT = getattr(UIA, "ScrollAmount_LargeIncrement", 3)
SCROLL_LARGE_DECREMENT = getattr(UIA, "ScrollAmount_LargeDecrement", 0)
SCROLL_NO_AMOUNT = getattr(UIA, "ScrollAmount_NoAmount", 2)

WINDOW_STATES = {"restore": 0, "normal": 0, "minimize": 1, "maximize": 2}


class ActionFailed(RuntimeError):
    """Mọi bậc của thang đều thất bại."""


@dataclass
class Ladder:
    """Thử lần lượt các bậc, ghi lại bậc nào chạy được và bậc nào hỏng vì sao."""

    action: str
    tried: list[str] = field(default_factory=list)

    def run(self, rungs: list[tuple[str, Callable[[], Any]]]) -> str:
        for name, attempt in rungs:
            try:
                result = attempt()
            except Exception as exc:  # noqa: BLE001 - bậc hỏng là chuyện bình thường
                self.tried.append(f"{name}: {type(exc).__name__}: {exc}".strip())
                continue
            if result is False:
                self.tried.append(f"{name}: không áp dụng được")
                continue
            time.sleep(SETTLE)
            detail = f" ({result})" if isinstance(result, str) and result else ""
            skipped = f" — đã bỏ qua: {'; '.join(self.tried)}" if self.tried else ""
            return f"OK: {self.action} qua {name}{detail}{skipped}"
        raise ActionFailed(
            f"{self.action} thất bại ở mọi bậc — " + "; ".join(self.tried or ["không có bậc nào khả dụng"])
        )


# --- Truy cập pattern ----------------------------------------------------------


def _invoke(element: Any) -> Any:
    return uia.pattern(element, UIA.UIA_InvokePatternId, UIA.IUIAutomationInvokePattern)


def _value(element: Any) -> Any:
    return uia.pattern(element, UIA.UIA_ValuePatternId, UIA.IUIAutomationValuePattern)


def _toggle(element: Any) -> Any:
    return uia.pattern(element, UIA.UIA_TogglePatternId, UIA.IUIAutomationTogglePattern)


def _selection_item(element: Any) -> Any:
    return uia.pattern(
        element, UIA.UIA_SelectionItemPatternId, UIA.IUIAutomationSelectionItemPattern
    )


def _expand_collapse(element: Any) -> Any:
    return uia.pattern(
        element, UIA.UIA_ExpandCollapsePatternId, UIA.IUIAutomationExpandCollapsePattern
    )


def _scroll(element: Any) -> Any:
    return uia.pattern(element, UIA.UIA_ScrollPatternId, UIA.IUIAutomationScrollPattern)


def _scroll_item(element: Any) -> Any:
    return uia.pattern(element, UIA.UIA_ScrollItemPatternId, UIA.IUIAutomationScrollItemPattern)


def _range_value(element: Any) -> Any:
    return uia.pattern(element, UIA.UIA_RangeValuePatternId, UIA.IUIAutomationRangeValuePattern)


def _window(element: Any) -> Any:
    return uia.pattern(element, UIA.UIA_WindowPatternId, UIA.IUIAutomationWindowPattern)


def _legacy(element: Any) -> Any:
    return uia.pattern(
        element, UIA.UIA_LegacyIAccessiblePatternId, UIA.IUIAutomationLegacyIAccessiblePattern
    )


# --- Bậc dùng lại nhiều nơi ----------------------------------------------------


def _focus(element: Any) -> str:
    element.SetFocus()
    time.sleep(0.05)
    return "đã focus"


def _host_window_rect(element: Any) -> tuple[int, int, int, int] | None:
    """Rect của cửa sổ top-level đang chứa phần tử."""
    from ctypes import byref, wintypes

    walker = uia.automation().ControlViewWalker
    node = element
    for _ in range(40):
        try:
            handle = int(node.CurrentNativeWindowHandle or 0)
        except Exception:
            handle = 0
        if handle and rawinput.user32.IsWindow(handle):
            box = wintypes.RECT()
            if rawinput.user32.GetWindowRect(handle, byref(box)):
                return box.left, box.top, box.right, box.bottom
            return None
        try:
            node = walker.GetParentElement(node)
        except Exception:
            return None
        if not node:
            return None
    return None


def _resolves_to(point: tuple[int, int], element: Any) -> bool:
    """Điểm này có thực sự thuộc phần tử đích (hoặc con của nó) không?"""
    from ctypes import wintypes

    try:
        hit = uia.automation().ElementFromPoint(wintypes.POINT(point[0], point[1]))
    except Exception:
        return False
    if not hit:
        return False
    walker = uia.automation().ControlViewWalker
    node = hit
    for _ in range(25):
        try:
            if uia.automation().CompareElements(node, element):
                return True
            node = walker.GetParentElement(node)
        except Exception:
            return False
        if not node:
            return False
    return False


def _click_center(element: Any, button: str = "left", clicks: int = 1) -> Any:
    """Click chuột thật, có kẹp biên và kiểm chứng điểm đến.

    BoundingRectangle KHÔNG bị cắt theo viewport: một hàng trong lưới cuộn ngang của SAP
    báo rect rộng tới x=3182 trong khi cửa sổ chỉ tới x=2571. Lấy tâm rect rồi click mù
    sẽ bấm ra ngoài ứng dụng — đo được là trúng cửa sổ chat trên màn hình khác. Đó vừa là
    lỗi "click trượt", vừa là rủi ro thật vì cú click rơi vào phần mềm không liên quan.
    """
    box = uia.rect(element, live=True)
    if box is None:
        return False

    window = _host_window_rect(element)
    if window:
        left, top = max(box[0], window[0]), max(box[1], window[1])
        right, bottom = min(box[2], window[2]), min(box[3], window[3])
        if right <= left or bottom <= top:
            return False  # phần tử nằm hoàn toàn ngoài vùng hiển thị của cửa sổ
        box = (left, top, right, bottom)

    point = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    if not _resolves_to(point, element):
        return False  # điểm đến không thuộc phần tử đích — thà hỏng còn hơn bấm nhầm

    try:
        element.SetFocus()
    except Exception:
        pass  # nhiều control không nhận focus nhưng vẫn click được
    rawinput.click_at(point[0], point[1], button=button, clicks=clicks)
    return f"toạ độ {point[0]},{point[1]} đã kẹp trong cửa sổ và kiểm chứng bằng ElementFromPoint"


# --- Các hành động -------------------------------------------------------------


def _act_click(element: Any, value: str | None) -> str:
    ladder = Ladder("click")

    def try_expand() -> Any:
        pattern = _expand_collapse(element)
        if not pattern:
            return False
        state = uia.cached(element, UIA.UIA_ExpandCollapseExpandCollapseStatePropertyId)
        if state == 1:
            pattern.Collapse()
            return "thu gọn"
        pattern.Expand()
        return "mở rộng"

    def try_keyboard() -> Any:
        if uia.cached(element, UIA.UIA_IsKeyboardFocusablePropertyId) is not True:
            return False
        element.SetFocus()
        time.sleep(0.05)
        rawinput.press_key("space")
        return "focus + Space"

    return ladder.run(
        [
            ("InvokePattern.Invoke", lambda: _invoke(element).Invoke() if _invoke(element) else False),
            ("TogglePattern.Toggle", lambda: _toggle(element).Toggle() if _toggle(element) else False),
            (
                "SelectionItemPattern.Select",
                lambda: _selection_item(element).Select() if _selection_item(element) else False,
            ),
            ("ExpandCollapsePattern", try_expand),
            (
                "LegacyIAccessible.DoDefaultAction",
                lambda: _legacy(element).DoDefaultAction() if _legacy(element) else False,
            ),
            ("focus + phím", try_keyboard),
            ("chuột tại BoundingRectangle", lambda: _click_center(element)),
        ]
    )


def _act_set_value(element: Any, value: str | None) -> str:
    if value is None:
        raise ValueError("set_value cần tham số value")
    ladder = Ladder("set_value")

    def try_value_pattern() -> Any:
        pattern = _value(element)
        if not pattern:
            return False
        if pattern.CurrentIsReadOnly:
            return False
        pattern.SetValue(value)
        return "không có synthetic input"

    def try_legacy() -> Any:
        pattern = _legacy(element)
        if not pattern:
            return False
        pattern.SetValue(value)
        return "LegacyIAccessible"

    def try_typing(click_first: bool) -> Any:
        if click_first:
            if _click_center(element) is False:
                return False
        else:
            element.SetFocus()
        time.sleep(0.08)
        rawinput.press_key("ctrl+a")
        rawinput.press_key("delete")
        rawinput.type_text(value)
        return "gõ phím thật"

    return ladder.run(
        [
            ("ValuePattern.SetValue", try_value_pattern),
            ("LegacyIAccessible.SetValue", try_legacy),
            ("focus + gõ", lambda: try_typing(False)),
            ("click + gõ", lambda: try_typing(True)),
        ]
    )


def _act_type(element: Any, value: str | None) -> str:
    """Gõ thêm vào cuối, giữ nguyên nội dung sẵn có."""
    if value is None:
        raise ValueError("type cần tham số value")
    ladder = Ladder("type")

    def try_focus_type() -> Any:
        element.SetFocus()
        time.sleep(0.08)
        rawinput.type_text(value)
        return "focus + gõ"

    def try_click_type() -> Any:
        if _click_center(element) is False:
            return False
        time.sleep(0.08)
        rawinput.type_text(value)
        return "click + gõ"

    return ladder.run([("focus + gõ", try_focus_type), ("click + gõ", try_click_type)])


def _act_toggle(element: Any, value: str | None) -> str:
    return Ladder("toggle").run(
        [
            ("TogglePattern.Toggle", lambda: _toggle(element).Toggle() if _toggle(element) else False),
            ("InvokePattern.Invoke", lambda: _invoke(element).Invoke() if _invoke(element) else False),
            ("chuột tại BoundingRectangle", lambda: _click_center(element)),
        ]
    )


def _act_select(element: Any, value: str | None) -> str:
    return Ladder("select").run(
        [
            (
                "SelectionItemPattern.Select",
                lambda: _selection_item(element).Select() if _selection_item(element) else False,
            ),
            ("InvokePattern.Invoke", lambda: _invoke(element).Invoke() if _invoke(element) else False),
            ("chuột tại BoundingRectangle", lambda: _click_center(element)),
        ]
    )


def _act_expand(element: Any, value: str | None, collapse: bool = False) -> str:
    label = "collapse" if collapse else "expand"

    def try_pattern() -> Any:
        pattern = _expand_collapse(element)
        if not pattern:
            return False
        pattern.Collapse() if collapse else pattern.Expand()
        return None

    return Ladder(label).run(
        [
            (f"ExpandCollapsePattern.{'Collapse' if collapse else 'Expand'}", try_pattern),
            ("InvokePattern.Invoke", lambda: _invoke(element).Invoke() if _invoke(element) else False),
            ("chuột tại BoundingRectangle", lambda: _click_center(element)),
        ]
    )


#: Sai số khi so sánh phần trăm cuộn; provider trả về float.
SCROLL_EPSILON = 0.05

#: Ngưỡng coi là đã chạm giới hạn cuộn theo từng hướng.
AT_LIMIT = {
    "down": lambda v, h: v >= 100 - SCROLL_EPSILON,
    "up": lambda v, h: 0 <= v <= SCROLL_EPSILON,
    "right": lambda v, h: h >= 100 - SCROLL_EPSILON,
    "left": lambda v, h: 0 <= h <= SCROLL_EPSILON,
}


def _scroll_position(pattern: Any) -> tuple[float, float]:
    def read(name: str) -> float:
        try:
            return float(getattr(pattern, name))
        except Exception:
            return -1.0

    return read("CurrentVerticalScrollPercent"), read("CurrentHorizontalScrollPercent")


def _act_scroll(element: Any, value: str | None) -> str:
    """Cuộn, có kiểm chứng.

    Giống ``WindowPattern``: ``ScrollPattern.Scroll`` có thể trả về thành công trong khi
    phần trăm cuộn không hề nhúc nhích (đo được trên Excel Online trong Edge). Nên mỗi
    bậc phải chứng minh vị trí đã đổi. Ngoại lệ hợp lệ duy nhất là khi đã cuộn hết về
    phía đó rồi — lúc đó không đổi mới là đúng, và ta nói rõ ra.
    """
    spec = (value or "down").strip().lower()

    # Chỉ trục được yêu cầu mới tính. Xét cả hai trục là sai: một dao động ngang sẽ làm
    # một lệnh cuộn dọc không nhúc nhích trông như thành công.
    axis = 1 if spec in ("left", "right") else 0

    def verified(action: Callable[[Any], None], label: str) -> Any:
        pattern = _scroll(element)
        if not pattern:
            return False
        before = _scroll_position(pattern)
        if spec in AT_LIMIT and AT_LIMIT[spec](*before):
            action(pattern)
            return f"{label} — đã ở giới hạn {spec}, không còn gì để cuộn"
        action(pattern)
        time.sleep(0.15)
        after = _scroll_position(_scroll(element) or pattern)
        if abs(after[axis] - before[axis]) <= SCROLL_EPSILON:
            return False  # provider nhận lệnh nhưng không cuộn — coi như bậc này hỏng
        # Một chữ số thập phân, không làm tròn về số nguyên: cuộn 0.0→0.4% mà in ra
        # "0% → 0%" thì báo cáo tự mâu thuẫn với chính chữ OK của nó.
        return f"{label} ({before[axis]:.1f}% → {after[axis]:.1f}%)"

    def try_percent() -> Any:
        try:
            percent = max(0.0, min(100.0, float(spec)))
        except ValueError:
            return False
        return verified(
            lambda pattern: pattern.SetScrollPercent(NO_SCROLL, percent), f"đặt vị trí {percent:g}%"
        )

    def try_direction() -> Any:
        if spec not in ("up", "down", "left", "right"):
            return False
        vertical = horizontal = SCROLL_NO_AMOUNT
        if spec == "down":
            vertical = SCROLL_LARGE_INCREMENT
        elif spec == "up":
            vertical = SCROLL_LARGE_DECREMENT
        elif spec == "right":
            horizontal = SCROLL_LARGE_INCREMENT
        else:
            horizontal = SCROLL_LARGE_DECREMENT
        return verified(lambda pattern: pattern.Scroll(horizontal, vertical), spec)

    def try_wheel() -> Any:
        if spec not in ("up", "down", "left", "right"):
            return False
        point = uia.center(element, live=True)
        if point is None:
            return False
        rawinput.wheel_at(point[0], point[1], spec)
        return f"lăn chuột tại {point[0]},{point[1]}"

    return Ladder("scroll").run(
        [
            ("ScrollPattern.SetScrollPercent", try_percent),
            ("ScrollPattern.Scroll", try_direction),
            ("lăn chuột thật", try_wheel),
        ]
    )


def _act_scroll_into_view(element: Any, value: str | None) -> str:
    return Ladder("scroll_into_view").run(
        [
            (
                "ScrollItemPattern.ScrollIntoView",
                lambda: _scroll_item(element).ScrollIntoView() if _scroll_item(element) else False,
            ),
            ("SetFocus", lambda: _focus(element)),
        ]
    )


def _act_set_number(element: Any, value: str | None) -> str:
    if value is None:
        raise ValueError("set_number cần tham số value")
    number = float(value)

    def try_range() -> Any:
        pattern = _range_value(element)
        if not pattern:
            return False
        pattern.SetValue(number)
        return f"đặt {number:g}"

    return Ladder("set_number").run(
        [
            ("RangeValuePattern.SetValue", try_range),
            (
                "ValuePattern.SetValue",
                lambda: _value(element).SetValue(str(value)) if _value(element) else False,
            ),
        ]
    )


#: Trạng thái Win32 mong đợi sau mỗi action, để kiểm chứng hậu điều kiện.
EXPECTED_STATE = {"restore": "normal", "normal": "normal", "minimize": "minimized", "maximize": "maximized"}

#: ShowWindow commands
SW = {"restore": 9, "normal": 9, "minimize": 6, "maximize": 3}

WM_CLOSE = 0x0010


def _handle_of(element: Any) -> int:
    try:
        return int(element.CurrentNativeWindowHandle or 0)
    except Exception:
        return 0


def _wait_for_state(handle: int, expected: str, timeout: float = 1.2) -> bool:
    from .perceive import window_visual_state

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if window_visual_state(handle) == expected:
            return True
        time.sleep(0.08)
    return False


def _act_window(element: Any, value: str | None, state: str) -> str:
    """Đổi trạng thái cửa sổ, có kiểm chứng.

    Không tin lời ``WindowPattern``: Notepad của Windows 11 chấp nhận
    ``SetWindowVisualState(Minimized)``, sau đó báo ``CurrentWindowVisualState = 1``,
    trong khi ``IsIconic()`` vẫn là False và cửa sổ vẫn hiện nguyên. Báo "OK" trong tình
    huống đó là false-success — thứ tệ nhất một tool có thể làm với agent. Nên mỗi bậc
    đều phải chứng minh hậu điều kiện bằng Win32 trước khi được tính là thành công.
    """
    handle = _handle_of(element)

    if state == "close":

        def try_close_pattern() -> Any:
            pattern = _window(element)
            if not pattern:
                return False
            pattern.Close()
            if handle and _wait_for_state(handle, "") is False and rawinput.user32.IsWindow(handle):
                return False
            return "đóng"

        def try_wm_close() -> Any:
            if not handle:
                return False
            rawinput.user32.PostMessageW(handle, WM_CLOSE, 0, 0)
            time.sleep(0.4)
            return "WM_CLOSE"

        return Ladder("close").run(
            [("WindowPattern.Close", try_close_pattern), ("PostMessage WM_CLOSE", try_wm_close)]
        )

    expected = EXPECTED_STATE[state]

    def try_pattern() -> Any:
        pattern = _window(element)
        if not pattern:
            return False
        pattern.SetWindowVisualState(WINDOW_STATES[state])
        if handle and not _wait_for_state(handle, expected):
            # Provider nhận lệnh nhưng cửa sổ không đổi — coi như bậc này hỏng.
            return False
        return state

    def try_show_window() -> Any:
        if not handle:
            return False
        rawinput.user32.ShowWindow(handle, SW[state])
        if not _wait_for_state(handle, expected):
            return False
        return f"ShowWindow → {expected}"

    return Ladder(state).run(
        [(f"WindowPattern.{state}", try_pattern), ("Win32 ShowWindow", try_show_window)]
    )


def _act_focus(element: Any, value: str | None) -> str:
    def restore_then_focus() -> Any:
        # SetFocus trên một cửa sổ minimize trả về thành công nhưng không khôi phục nó,
        # nên nội dung vẫn không tồn tại. Phải bung ra trước.
        from .perceive import window_visual_state

        try:
            handle = element.CurrentNativeWindowHandle or 0
        except Exception:
            return False
        if window_visual_state(handle) != "minimized":
            return False
        # Đi qua _act_window để được kiểm chứng hậu điều kiện + fallback ShowWindow.
        _act_window(element, None, "restore")
        element.SetFocus()
        return "đã bung cửa sổ khỏi trạng thái minimize"

    return Ladder("focus").run(
        [
            ("WindowPattern.restore + SetFocus", restore_then_focus),
            ("SetFocus", lambda: _focus(element)),
            ("chuột tại BoundingRectangle", lambda: _click_center(element)),
        ]
    )


def _act_click_physical(element: Any, value: str | None) -> str:
    """Bỏ qua mọi control pattern, click chuột thật ngay.

    Cần thiết khi provider *nhận* pattern và báo thành công nhưng ứng dụng không phản
    ứng — SAP Business ByDesign là ví dụ: `SelectionItemPattern.Select` đổi đúng trạng
    thái selected của hàng, nhưng panel Details chỉ nạp lại khi có sự kiện chuột thật.
    Thang fallback không tự cứu được vì bậc 1 đã "thành công" nên không bao giờ tụt xuống.
    """
    return Ladder("click_physical").run(
        [("chuột thật tại BoundingRectangle", lambda: _click_center(element))]
    )


def _safe_point(element: Any) -> tuple[int, int] | None:
    """Tâm phần tử, đã kẹp vào cửa sổ chủ và kiểm chứng bằng ElementFromPoint."""
    box = uia.rect(element, live=True)
    if box is None:
        return None
    window = _host_window_rect(element)
    if window:
        left, top = max(box[0], window[0]), max(box[1], window[1])
        right, bottom = min(box[2], window[2]), min(box[3], window[3])
        if right <= left or bottom <= top:
            return None
        box = (left, top, right, bottom)
    point = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    return point if _resolves_to(point, element) else None


def _act_drag(element: Any, value: str | None) -> str:
    """Kéo phần tử này tới một đích.

    ``value`` là ``"x,y"`` (toạ độ màn hình) hoặc ``"id:N"`` (id của phần tử đích).
    UIA không có pattern nào cho kéo–thả, nên đây luôn là chuột thật; cả hai đầu đều
    được kẹp biên và kiểm chứng danh tính trước khi bơm sự kiện.
    """
    if not value:
        raise ValueError("drag cần value: 'x,y' hoặc 'id:N'")
    spec = value.strip()

    if spec.lower().startswith("id:"):
        from .registry import REGISTRY

        target = REGISTRY.get(int(spec[3:]))
        end = _safe_point(target)
        if end is None:
            return Ladder("drag").run([("đích không xác định được", lambda: False)])
        end_label = f"id:{spec[3:]}"
    else:
        try:
            xs, ys = spec.split(",")
            end = (int(xs), int(ys))
        except Exception:
            raise ValueError(f"value không hợp lệ: {value!r} — cần 'x,y' hoặc 'id:N'") from None
        end_label = f"{end[0]},{end[1]}"

    def try_drag() -> Any:
        start = _safe_point(element)
        if start is None:
            return False
        rawinput.drag(start, end)
        return f"{start[0]},{start[1]} → {end_label}"

    return Ladder("drag").run([("chuột thật (UIA không có pattern kéo–thả)", try_drag)])


def _act_add_to_selection(element: Any, value: str | None) -> str:
    """Thêm phần tử vào vùng chọn hiện có thay vì thay thế nó — tức multi-select."""

    def try_pattern() -> Any:
        pattern = _selection_item(element)
        if not pattern:
            return False
        pattern.AddToSelection()
        return "SelectionItemPattern.AddToSelection"

    def try_ctrl_click() -> Any:
        point = _safe_point(element)
        if point is None:
            return False
        try:
            element.SetFocus()
        except Exception:
            pass
        # Ctrl+click là cách người dùng thật mở rộng vùng chọn khi provider không hỗ trợ.
        rawinput.hold_key("ctrl", lambda: rawinput.click_at(point[0], point[1]))
        return f"Ctrl+click tại {point[0]},{point[1]}"

    return Ladder("add_to_selection").run(
        [("SelectionItemPattern.AddToSelection", try_pattern), ("Ctrl + click chuột thật", try_ctrl_click)]
    )


def _act_right_click(element: Any, value: str | None) -> str:
    return Ladder("right_click").run(
        [("chuột phải tại BoundingRectangle", lambda: _click_center(element, button="right"))]
    )


def _act_double_click(element: Any, value: str | None) -> str:
    return Ladder("double_click").run(
        [("nháy đúp tại BoundingRectangle", lambda: _click_center(element, clicks=2))]
    )


ACTIONS: dict[str, Callable[[Any, str | None], str]] = {
    "click": _act_click,
    "invoke": _act_click,
    "double_click": _act_double_click,
    "right_click": _act_right_click,
    "click_physical": _act_click_physical,
    "drag": _act_drag,
    "add_to_selection": _act_add_to_selection,
    "set_value": _act_set_value,
    "type": _act_type,
    "toggle": _act_toggle,
    "select": _act_select,
    "expand": _act_expand,
    "collapse": lambda element, value: _act_expand(element, value, collapse=True),
    "scroll": _act_scroll,
    "scroll_into_view": _act_scroll_into_view,
    "set_number": _act_set_number,
    "focus": _act_focus,
    "close": lambda element, value: _act_window(element, value, "close"),
    "restore": lambda element, value: _act_window(element, value, "restore"),
    "minimize": lambda element, value: _act_window(element, value, "minimize"),
    "maximize": lambda element, value: _act_window(element, value, "maximize"),
}


def act(element: Any, action: str, value: str | None = None) -> str:
    handler = ACTIONS.get(action.strip().lower())
    if handler is None:
        raise ValueError(f"action phải là một trong {sorted(ACTIONS)}")
    return handler(element, value)
