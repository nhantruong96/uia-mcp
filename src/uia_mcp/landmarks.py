"""Điểm neo: đổi một lần quét đắt lấy hàng loạt lần trỏ rẻ.

Quét cây là thứ đắt, không phải bộ lọc. Đo trên Revit 2027 có model: quét toàn cây
701 phần tử mất **16,3 giây**, và ngay cả ``FindAll`` đã lọc theo control type vẫn mất
**6,2 giây** — vì chi phí nằm ở việc duyệt, bộ lọc không giúp gì.

Trong khi đó ``ElementFromPoint`` chỉ tốn **~2 ms**.

Nên với những ứng dụng nặng và dùng thường xuyên, cách đúng là: quét *một lần*, ghi lại
toạ độ của mọi phần tử có tên, rồi những lần sau giải lại bằng toạ độ. Toạ độ có thể cũ
(cửa sổ di chuyển, panel đổi layout) nên mỗi lần dùng đều phải **kiểm chứng lại danh tính**
bằng chính ``ElementFromPoint``; sai thì báo hỏng để caller quay về đường quét chậm và
ghi đè điểm neo mới.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import time
from pathlib import Path
from typing import Any

from . import uia
from .uia import UIA

user32 = ctypes.WinDLL("user32", use_last_error=True)

STORE = Path(os.environ.get("LOCALAPPDATA", ".")) / "uia-mcp" / "landmarks.json"

#: Chấp nhận khi phần tử dưới điểm neo là chính nó hoặc con cháu của nó. Điểm giữa một
#: Button thường rơi vào Text/Image bên trong; điểm giữa một panel lớn (Project Browser
#: của Revit là web view) có thể sâu hơn chục cấp. Đi lên đủ xa, nhưng vẫn hữu hạn — một
#: điểm thuộc ứng dụng khác sẽ đi tới gốc của nó mà không bao giờ khớp tên, nên vẫn an toàn.
VERIFY_DEPTH = 14


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def app_key(window: Any) -> str:
    """Khoá theo tiến trình, không theo tiêu đề.

    Tiêu đề của Revit đổi theo model đang mở nên vô dụng làm khoá; tên file thực thi thì
    ổn định.
    """
    try:
        pid = int(window.CurrentProcessId)
    except Exception:
        return "unknown"
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFO
    if not handle:
        return f"pid{pid}"
    try:
        size = ctypes.c_ulong(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
        return f"pid{pid}"
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _entry_key(control_type: str, name: str) -> str:
    return f"{control_type}:{name}"


def capture(window: Any, min_area: int = 1, merge: bool = False) -> dict:
    """Quét một lần, ghi toạ độ mọi phần tử có tên. Đắt — chỉ chạy khi cần.

    Ghi cả rect cửa sổ lúc chụp, để lần sau biết cửa sổ đã bị di chuyển hay đổi kích thước
    và điểm neo nhiều khả năng đã lệch.

    ``merge=True`` giữ lại điểm neo của những lần quét trước thay vì thay thế chúng. Cần
    cho giao diện chỉ lộ một phần tại một thời điểm: ribbon Revit chỉ dựng cây cho tab
    đang mở, nên muốn có điểm neo của nhiều tab thì phải quét từng tab rồi gộp. Điểm neo
    trùng tên thì lần quét mới thắng. Gộp không làm mất an toàn: mỗi lần dùng, resolve()
    vẫn kiểm chứng lại danh tính tại toạ độ đó, nên điểm neo của tab đang đóng sẽ báo
    hỏng chứ không trả về nhầm phần tử.
    """
    automation = uia.automation()
    started = time.perf_counter()
    found = window.FindAllBuildCache(
        UIA.TreeScope_Subtree, automation.CreateTrueCondition(), uia.cache_request()
    )

    entries: dict[str, dict] = {}
    for index in range(found.Length):
        element = found.GetElement(index)
        name = str(uia.cached(element, UIA.UIA_NamePropertyId) or "").strip()
        box = uia.rect(element)
        if not name or box is None:
            continue
        if (box[2] - box[0]) * (box[3] - box[1]) < min_area:
            continue
        control_type = uia.control_type_name(element)
        entries[_entry_key(control_type, name)] = {
            "point": [(box[0] + box[2]) // 2, (box[1] + box[3]) // 2],
            "rect": list(box),
            "type": control_type,
            "name": name,
        }

    try:
        handle = int(window.CurrentNativeWindowHandle or 0)
    except Exception:
        handle = 0
    window_box = None
    if handle:
        rect = ctypes.wintypes.RECT()
        if user32.GetWindowRect(handle, ctypes.byref(rect)):
            window_box = [rect.left, rect.top, rect.right, rect.bottom]

    store = _load()
    key = app_key(window)
    if merge:
        kept = dict(store.get(key, {}).get("entries", {}))
        kept.update(entries)
        entries = kept
    store[key] = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scan_ms": round((time.perf_counter() - started) * 1000),
        "window_rect": window_box,
        "entries": entries,
    }
    _save(store)
    return store[key]


def _matches(element: Any, expected_name: str) -> bool:
    walker = uia.automation().ControlViewWalker
    node = element
    for _ in range(VERIFY_DEPTH):
        try:
            if str(node.CurrentName or "").strip() == expected_name:
                return True
            node = walker.GetParentElement(node)
        except Exception:
            return False
        if not node:
            return False
    return False


def _describe_hit(element: Any) -> str:
    try:
        return f"{element.CurrentLocalizedControlType} {str(element.CurrentName)[:40]!r}"
    except Exception:
        return "(không đọc được)"


def resolve(
    window: Any, name: str, control_type: str | None = None, activate: bool = False
) -> tuple[Any, str]:
    """Giải một điểm neo thành phần tử sống. Trả về (element|None, ghi chú).

    Điểm neo là toạ độ **màn hình**, và ``ElementFromPoint`` luôn trả về thứ nằm trên
    cùng tại điểm đó — bất kể ta đang định nói tới cửa sổ nào. Nếu cửa sổ đích bị cửa sổ
    khác che, điểm neo sẽ trỏ sang ứng dụng khác. Vì vậy phải kiểm chứng danh tính, và
    thà báo hỏng còn hơn trả về nhầm: click nhầm sang app khác là tai nạn thật.
    """
    store = _load().get(app_key(window))
    if not store:
        return None, "chưa có điểm neo cho ứng dụng này — gọi landmark_capture() trước"

    try:
        handle = int(window.CurrentNativeWindowHandle or 0)
    except Exception:
        handle = 0
    if handle and user32.GetForegroundWindow() != handle:
        if activate:
            user32.SetForegroundWindow(handle)
            time.sleep(0.35)
        else:
            return None, (
                "cửa sổ đích không ở trên cùng — điểm neo là toạ độ màn hình nên sẽ trỏ "
                "vào cửa sổ đang che nó. Gọi lại với activate=True để đưa nó lên trước."
            )

    entries = store.get("entries", {})
    candidates = []
    if control_type:
        entry = entries.get(_entry_key(control_type, name))
        if entry:
            candidates.append(entry)
    if not candidates:
        folded = name.casefold()
        exact = [e for e in entries.values() if e["name"].casefold() == folded]
        partial = [e for e in entries.values() if folded in e["name"].casefold()]
        candidates = exact or partial
    if not candidates:
        return None, f"không có điểm neo nào tên {name!r}"

    automation = uia.automation()
    seen = []
    for entry in candidates[:5]:
        point = ctypes.wintypes.POINT(entry["point"][0], entry["point"][1])
        try:
            hit = automation.ElementFromPoint(point)
        except Exception:
            continue
        if not hit:
            continue
        if not _matches(hit, entry["name"]):
            seen.append(f"{tuple(entry['point'])} → {_describe_hit(hit)}")
            continue
        try:
            cached = hit.BuildUpdatedCache(uia.cache_request())
        except Exception:
            cached = hit
        return cached, f"giải bằng điểm neo tại {tuple(entry['point'])}"

    return None, (
        f"điểm neo của {name!r} đã cũ. Dưới toạ độ cũ hiện là: {'; '.join(seen) or '(không có gì)'}. "
        f"Tìm lại bằng find(), rồi landmark_capture() để cập nhật."
    )


def summary(window: Any) -> str:
    key = app_key(window)
    store = _load().get(key)
    if not store:
        return f"{key}: chưa có điểm neo nào"
    entries = store.get("entries", {})
    moved = ""
    try:
        handle = int(window.CurrentNativeWindowHandle or 0)
        rect = ctypes.wintypes.RECT()
        if handle and user32.GetWindowRect(handle, ctypes.byref(rect)):
            now = [rect.left, rect.top, rect.right, rect.bottom]
            if store.get("window_rect") and now != store["window_rect"]:
                moved = "  ⚠ cửa sổ đã đổi vị trí/kích thước so với lúc chụp — điểm neo có thể lệch"
    except Exception:
        pass
    return (
        f"{key}: {len(entries)} điểm neo, chụp lúc {store.get('captured_at')} "
        f"(lần quét đó mất {store.get('scan_ms')} ms){moved}"
    )
