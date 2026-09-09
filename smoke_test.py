"""Kiểm thử toàn bộ vòng lặp trên một Notepad do chính script này mở và đóng.

Không đụng tới bất kỳ cửa sổ nào khác của người dùng.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import io
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ctypes.windll.shcore.SetProcessDpiAwareness(2)

from uia_mcp import actions, perceive, rawinput, text  # noqa: E402
from uia_mcp.registry import REGISTRY  # noqa: E402
from uia_mcp.sta import STA  # noqa: E402

SAMPLE = "Điều khiển Windows không cần ảnh chụp màn hình."
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def find_notepad_hwnd() -> int:
    def work() -> int:
        automation = __import__("uia_mcp.uia", fromlist=["uia"]).automation()
        walker = automation.ControlViewWalker
        child = walker.GetFirstChildElement(automation.GetRootElement())
        while child:
            try:
                if child.CurrentClassName == "Notepad":
                    return child.CurrentNativeWindowHandle
            except Exception:
                pass
            child = walker.GetNextSiblingElement(child)
        return 0

    for _ in range(80):
        handle = STA.call(work)
        if handle:
            return handle
        time.sleep(0.1)
    raise RuntimeError("không tìm thấy cửa sổ Notepad")


def row_for(table: str, predicate) -> tuple[int, str] | None:
    for line in table.splitlines():
        parts = line.split("|")
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        if predicate(parts):
            return int(parts[0]), line
    return None


print("=== 1. list_windows ===")
windows = STA.call(perceive.list_windows)
check("liệt kê được cửa sổ", windows.count("\n") >= 1, f"{windows.count(chr(10))} dòng")

print("\n=== 2. mở Notepad và observe ===")
process = subprocess.Popen(["notepad.exe"])
hwnd = None
try:
    hwnd = find_notepad_hwnd()
    time.sleep(0.4)

    started = time.perf_counter()
    table = STA.call(perceive.observe, window=str(hwnd), filter="interactive")
    elapsed = (time.perf_counter() - started) * 1000
    print(table[:600])
    check("observe trả về dòng", len(table.splitlines()) > 3, f"{len(table.splitlines())} dòng, {elapsed:.0f} ms")
    check("có cột patterns", "invoke" in table)

    print("\n=== 3. act(set_value) — ghi text không synthetic input ===")
    doc = row_for(table, lambda parts: "value" in parts[4] and parts[1] in ("Document", "Edit"))
    check("tìm thấy vùng soạn thảo", doc is not None, doc[1] if doc else "")
    if doc:
        result = STA.call(actions.act, REGISTRY.get(doc[0]), "set_value", SAMPLE)
        print(f"  {result}")
        check("dùng bậc 1 (ValuePattern)", "ValuePattern.SetValue" in result, result[:80])

        print("\n=== 4. read_text — thay OCR ===")
        content = STA.call(text.read_text, REGISTRY.get(doc[0]))
        print(f"  {content[:200]}")
        check("đọc lại đúng nội dung, dấu tiếng Việt nguyên vẹn", SAMPLE in content)

    print("\n=== 5. act(click) — đổi trạng thái không chuột/phím ===")

    def count_tabs() -> int:
        table = STA.call(perceive.observe, window=str(hwnd), filter="all", max_elements=400)
        return sum(1 for line in table.splitlines() if line.split("|")[1:2] == ["TabItem"])

    before = count_tabs()
    fresh = STA.call(perceive.observe, window=str(hwnd), filter="interactive")
    new_tab = row_for(fresh, lambda parts: parts[2].startswith("Add New Tab"))
    check("tìm thấy nút 'Add New Tab'", new_tab is not None)
    if new_tab:
        result = STA.call(actions.act, REGISTRY.get(new_tab[0]), "click")
        print(f"  {result}")
        check("dùng bậc 1 (InvokePattern)", "InvokePattern.Invoke" in result, result[:80])
        time.sleep(0.5)
        after = count_tabs()
        check("số tab tăng", after > before, f"{before} -> {after}")

    print("\n=== 6. ID ổn định giữa hai lần observe ===")
    first = STA.call(perceive.observe, window=str(hwnd), filter="interactive")
    second = STA.call(perceive.observe, window=str(hwnd), filter="interactive")
    ids_first = [line.split("|")[0] for line in first.splitlines() if line.split("|")[0].isdigit()]
    ids_second = [line.split("|")[0] for line in second.splitlines() if line.split("|")[0].isdigit()]
    check("ID không đổi khi UI không đổi", ids_first == ids_second, f"{len(ids_first)} phần tử")

    print("\n=== 7. describe_at trên tâm cửa sổ ===")
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    described = STA.call(
        perceive.describe_at, (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
    )
    print(f"  {described.splitlines()[-1][:120]}")
    check("describe_at trả về phần tử", "|" in described.splitlines()[-1])

    print("\n=== 8. cửa sổ minimize: cảnh báo + restore ===")
    # Hồi quy cho bug tìm được lúc test phase 1: cửa sổ minimize không render nên cây UI
    # co lại chỉ còn khung. Trả về cây rỗng mà không nói gì sẽ khiến agent kết luận nhầm
    # "ứng dụng này không có UI". SetFocus cũng báo thành công mà không bung cửa sổ ra.
    shell = STA.call(perceive.observe, window=str(hwnd), filter="all", max_elements=80)
    window_row = row_for(shell, lambda parts: parts[1] == "Window")
    check("tìm thấy phần tử Window", window_row is not None)

    content_before = row_for(shell, lambda parts: parts[1] == "Document")
    check("có Document khi cửa sổ hiện bình thường", content_before is not None)

    if window_row:
        print(f"  {STA.call(actions.act, REGISTRY.get(window_row[0]), 'minimize')}")
        time.sleep(0.6)

        minimized = STA.call(perceive.observe, window=str(hwnd), filter="all", max_elements=80)
        check("header báo state=minimized", "state=minimized" in minimized.splitlines()[0])
        check("có dòng CẢNH BÁO", "CẢNH BÁO" in minimized)
        # Không assert việc cây có co lại hay không: đó là hành vi của ứng dụng và của
        # Windows, không phải của server này, và nó còn phụ thuộc thời điểm. Trách nhiệm
        # của ta chỉ là cảnh báo. Ghi lại con số để theo dõi hiện tượng.
        shrunk = len([l for l in minimized.splitlines() if l.split("|")[0].isdigit()])
        full = len([l for l in shell.splitlines() if l.split("|")[0].isdigit()])
        print(f"  (thông tin) số phần tử: {full} khi hiện → {shrunk} khi minimize")

        result = STA.call(actions.act, REGISTRY.get(window_row[0]), "restore")
        print(f"  {result}")
        check("restore dùng WindowPattern", "WindowPattern" in result, result[:70])
        time.sleep(0.6)

        restored = STA.call(perceive.observe, window=str(hwnd), filter="all", max_elements=80)
        check("header hết state=minimized", "state=minimized" not in restored.splitlines()[0])
        check(
            "Document quay lại sau restore",
            row_for(restored, lambda parts: parts[1] == "Document") is not None,
        )

        # focus phải tự bung cửa sổ, vì SetFocus trên cửa sổ minimize không khôi phục gì
        STA.call(actions.act, REGISTRY.get(window_row[0]), "minimize")
        time.sleep(0.6)
        focus_result = STA.call(actions.act, REGISTRY.get(window_row[0]), "focus")
        print(f"  {focus_result}")
        # Phải kiểm tra bậc ĐƯỢC CHỌN, không phải chuỗi "restore" xuất hiện đâu đó —
        # nó cũng nằm trong phần "đã bỏ qua" khi bậc đó không áp dụng được.
        check(
            "focus tự bung cửa sổ minimize",
            focus_result.split(" — ")[0].startswith("OK: focus qua WindowPattern.restore"),
            focus_result[:90],
        )
        time.sleep(0.5)
        check(
            "Document có mặt sau focus",
            row_for(
                STA.call(perceive.observe, window=str(hwnd), filter="all", max_elements=80),
                lambda parts: parts[1] == "Document",
            )
            is not None,
        )

    print("\n=== 9. find: tìm ở bất kỳ độ sâu nào ===")
    by_type = STA.call(perceive.find, query="MenuItem", window=str(hwnd), by="type")
    check("find by=type tìm được MenuItem", row_for(by_type, lambda p: p[1] == "MenuItem") is not None)

    by_name = STA.call(perceive.find, query="add new tab", window=str(hwnd))
    hit = row_for(by_name, lambda p: p[2].startswith("Add New Tab"))
    check("find by=auto không phân biệt hoa thường", hit is not None)

    by_pattern = STA.call(perceive.find, query="text", window=str(hwnd), by="pattern")
    check(
        "find by=pattern tìm được vùng có TextPattern",
        row_for(by_pattern, lambda p: "text" in p[4]) is not None,
    )

    # find phải trả về CÙNG id với observe cho cùng một phần tử — nếu không, model sẽ
    # tác động lên phần tử khác với cái nó vừa tìm thấy.
    seen = STA.call(perceive.observe, window=str(hwnd), filter="interactive")
    from_observe = row_for(seen, lambda p: p[2].startswith("Add New Tab"))
    check(
        "id của find khớp id của observe",
        hit is not None and from_observe is not None and hit[0] == from_observe[0],
        f"find={hit[0] if hit else '?'} observe={from_observe[0] if from_observe else '?'}",
    )

    # Khớp chính xác phải xếp trước khớp một phần: 'File' cũng là tiền tố của nhiều thứ.
    ranked = STA.call(perceive.find, query="File", window=str(hwnd), by="name", limit=10)
    ranked_rows = [line for line in ranked.splitlines() if line.split("|")[0].isdigit()]
    first_name = ranked_rows[0].split("|")[2] if ranked_rows else ""
    partial = [r for r in ranked_rows if r.split("|")[2].casefold() != "file"]
    check(
        "khớp chính xác xếp trước khớp một phần",
        first_name.casefold() == "file",
        f"đầu bảng={first_name!r}, có {len(partial)} khớp một phần phía sau",
    )

    for bad, label in (("Khongcoloainay", "type"), ("khongcopattern", "pattern")):
        try:
            STA.call(perceive.find, query=bad, window=str(hwnd), by=label)
            check(f"find by={label} báo lỗi khi giá trị sai", False, "không ném lỗi")
        except ValueError as exc:
            check(f"find by={label} báo lỗi khi giá trị sai", bad in str(exc), str(exc)[:60])

    print("\n=== 10. find(within=…) và read_table ===")

    def count_hits(text_block: str) -> int:
        return len([l for l in text_block.splitlines() if l.split("|")[0].isdigit()])

    all_buttons = STA.call(perceive.find, query="Button", window=str(hwnd), by="type", limit=200)
    tree = STA.call(perceive.observe, window=str(hwnd), filter="all", max_elements=80)
    menubar = row_for(tree, lambda p: p[1] == "MenuBar")
    check("tìm thấy MenuBar để giới hạn phạm vi", menubar is not None)
    if menubar:
        # MenuBar chứa MenuItem chứ không chứa Button, nên kiểm hai chiều:
        # loại nó CÓ phải ra kết quả, loại nó KHÔNG có phải bị loại sạch.
        all_items = STA.call(perceive.find, query="MenuItem", window=str(hwnd), by="type", limit=200)
        scoped_items = STA.call(
            perceive.find, query="MenuItem", window=str(hwnd), by="type", limit=200, within=menubar[0]
        )
        check(
            "within vẫn thấy thứ nằm trong phạm vi",
            0 < count_hits(scoped_items) <= count_hits(all_items),
            f"MenuItem: toàn cửa sổ={count_hits(all_items)} → trong MenuBar={count_hits(scoped_items)}",
        )

        scoped_buttons = STA.call(
            perceive.find, query="Button", window=str(hwnd), by="type", limit=200, within=menubar[0]
        )
        check(
            "within loại thứ nằm ngoài phạm vi",
            count_hits(all_buttons) > 0 and count_hits(scoped_buttons) < count_hits(all_buttons),
            f"Button: toàn cửa sổ={count_hits(all_buttons)} → trong MenuBar={count_hits(scoped_buttons)}",
        )
        check("header nói rõ phạm vi", scoped_items.splitlines()[0].startswith("trong id="))

    # read_table trên phần tử không phải lưới phải chỉ đường, không chỉ báo lỗi cụt.
    document = row_for(
        STA.call(perceive.observe, window=str(hwnd), filter="interactive"),
        lambda p: p[1] == "Document",
    )
    if document:
        not_grid = STA.call(text.read_table, REGISTRY.get(document[0]))
        check(
            "read_table trên phần tử không có lưới thì gợi ý cách tìm lưới",
            "GridPattern" in not_grid and "find(" in not_grid,
            not_grid[:70],
        )

    print("\n=== 11. điểm neo ===")
    from uia_mcp import landmarks  # noqa: PLC0415 - chỉ dùng ở đây

    window_element = STA.call(perceive.resolve_window, str(hwnd))
    captured = STA.call(landmarks.capture, window_element)
    check("chụp được điểm neo", len(captured["entries"]) > 3, f"{len(captured['entries'])} điểm")
    check("khoá theo tên tiến trình", STA.call(landmarks.app_key, window_element) == "notepad.exe")

    started = time.perf_counter()
    element, note = STA.call(landmarks.resolve, window_element, "Add New Tab", None, True)
    elapsed = (time.perf_counter() - started) * 1000
    check("giải được điểm neo", element is not None, f"{elapsed:.0f} ms — {note[:50]}")

    slow_started = time.perf_counter()
    STA.call(perceive.find, query="Add New Tab", window=str(hwnd), by="name")
    slow_elapsed = (time.perf_counter() - slow_started) * 1000
    print(f"  (thông tin) điểm neo {elapsed:.0f} ms  vs  find() {slow_elapsed:.0f} ms")

    # Điểm neo trỏ nhầm phải bị TỪ CHỐI, không được trả về phần tử sai.
    store = landmarks._load()
    store["notepad.exe"]["entries"]["Button:Add New Tab"]["point"] = [3, 3]
    landmarks._save(store)
    stale, stale_note = STA.call(landmarks.resolve, window_element, "Add New Tab", None, True)
    check("điểm neo lệch bị từ chối", stale is None, stale_note[:60])
    check("thông báo nói rõ dưới toạ độ đó là gì", "hiện là" in stale_note or "đã cũ" in stale_note)

    print("\n=== 12. dọn dẹp: xoá nội dung và đóng tab thừa ===")
    # Notepad của Windows 11 khôi phục session, nên phải trả nó về trạng thái sạch,
    # nếu không lần mở sau sẽ đầy tab rác. Vòng lặp này cũng là một bài test thật:
    # observe -> act -> observe lại, nhiều lượt liên tiếp.
    # Nút "Close Tab" chỉ tồn tại cho tab đang active/hover, nên nó biến mất sau lần
    # đóng đầu tiên. Ctrl+W đóng tab đang active và luôn có mặt.
    for _ in range(8):
        current = STA.call(perceive.observe, window=str(hwnd), filter="interactive")
        document = row_for(current, lambda parts: parts[1] == "Document")
        if document:
            STA.call(actions.act, REGISTRY.get(document[0]), "set_value", "")
            STA.call(actions.act, REGISTRY.get(document[0]), "focus")
        tabs = [line for line in current.splitlines() if line.split("|")[1:2] == ["TabItem"]]
        if len(tabs) <= 1:
            break
        rawinput.press_key("ctrl+w")
        time.sleep(0.4)
    final = STA.call(perceive.observe, window=str(hwnd), filter="interactive")
    remaining = [line for line in final.splitlines() if line.split("|")[1:2] == ["TabItem"]]
    check("chỉ còn 1 tab sạch", len(remaining) <= 1, f"{len(remaining)} tab")

finally:
    # Chỉ giết đúng tiến trình Notepad của cửa sổ này — không đụng Notepad của người dùng.
    target_pid = None
    if hwnd:
        pid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        target_pid = pid.value
    if target_pid:
        subprocess.run(["taskkill", "/F", "/PID", str(target_pid)], capture_output=True)
    else:
        process.kill()
    print("\nđã đóng Notepad do script này mở")

print("\n" + "=" * 60)
if failures:
    print(f"THẤT BẠI: {len(failures)} — " + "; ".join(failures))
    sys.exit(1)
print("TẤT CẢ PASS")
