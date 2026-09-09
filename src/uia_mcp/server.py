"""MCP server: điều khiển Windows không cần ảnh chụp màn hình.

Mọi tool đều marshal công việc vào một thread STA duy nhất (xem :mod:`uia_mcp.sta`).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__, actions, landmarks, perceive, text
from . import notifications as notifications_module
from . import screenshot as screenshot_module
from .registry import REGISTRY
from .sta import STA

mcp = MCPServer(
    "uia-mcp",
    version=__version__,
    instructions=(
        "Điều khiển Windows qua cây trợ năng UI Automation.\n"
        "\n"
        "THỨ TỰ ƯU TIÊN, không được đảo:\n"
        "1. MCP riêng của ứng dụng (API) — revit-mcp, Excel-MCP, Navisworks, Outlook, "
        "ACC, SAP2000… Nhanh nhất, tin cậy nhất, không cần ứng dụng mở cửa sổ.\n"
        "2. UIA — các tool ở server này, cho mọi ứng dụng còn lại. Gọi observe() hoặc "
        "find() để lấy id, rồi act()/read_text() trên id đó; không bao giờ đoán toạ độ.\n"
        "3. screenshot() — CHỈ khi cả hai bậc trên đều bó tay, ví dụ nội dung vẽ trên "
        "canvas (viewport 3D, lưới Excel Online, game). Tool này bắt khai rõ đã thử gì.\n"
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
MUTATING = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


def _run(fn: Any, *args: Any, timeout: float = 20.0, **kwargs: Any) -> str:
    """Chạy trên thread STA và biến lỗi thành text để model đọc được."""
    try:
        return STA.call(fn, *args, timeout=timeout, **kwargs)
    except Exception as exc:  # noqa: BLE001 - model cần thấy lỗi, không cần traceback
        return f"LỖI: {type(exc).__name__}: {exc}"


@mcp.tool(annotations=READ_ONLY)
def list_windows() -> str:
    """Liệt kê mọi cửa sổ top-level đang mở (hwnd, class, pid, tiêu đề, cửa sổ nào đang focus).

    Rẻ. Dùng để chọn giá trị cho tham số `window` của observe().
    """
    return _run(perceive.list_windows)


@mcp.tool(annotations=READ_ONLY)
def observe(window: str = "focused", filter: str = "interactive", max_elements: int = 250) -> str:
    """Đọc trạng thái UI từ cây trợ năng của Windows. KHÔNG chụp ảnh màn hình.

    Trả về bảng `id|type|name|state|patterns`. Dùng `id` đó cho act() và read_text() —
    không bao giờ cần đoán toạ độ.

    Cột `state` cho biết những thứ ảnh chụp không nói chắc được: focused, disabled,
    on/off, selected, expanded/collapsed, giá trị thật của ô nhập, phần trăm cuộn.
    Cột `patterns` cho biết phần tử đó chấp nhận hành động nào.

    Tham số:
        window: "focused" (mặc định), "desktop", một hwnd dạng số, hoặc một phần tiêu đề.
        filter: "interactive" (mặc định, chỉ control hành động được),
                "text" (nội dung đọc được), "table" (lưới/bảng, dùng trước read_table),
                "all" (mọi thứ đang hiển thị).
        max_elements: chặn trên số dòng trả về.
    """
    return _run(perceive.observe, window=window, filter=filter, max_elements=max_elements)


@mcp.tool(annotations=READ_ONLY)
def find(
    query: str,
    window: str = "focused",
    by: str = "auto",
    limit: int = 20,
    include_offscreen: bool = False,
    within: int | None = None,
) -> str:
    """Tìm phần tử ở BẤT KỲ độ sâu nào và trả về id dùng được ngay cho act()/read_text().

    Dùng cái này thay vì tăng max_elements của observe(). observe() cắt theo thứ tự duyệt
    cây nên thứ nằm sâu không bao giờ tới lượt — bảng thư của Outlook là phần tử 196/325,
    tab thật của Edge nằm dưới `EdgeTabStrip`. find() không bị giới hạn đó.

    Tham số:
        query: chuỗi cần tìm (không phân biệt hoa thường).
        window: "focused" (mặc định), "desktop", hwnd dạng số, hoặc một phần tiêu đề.
        by:
          "auto"          – khớp name, AutomationId hoặc ClassName (mặc định)
          "name"          – chỉ tên hiển thị
          "class"         – ClassName, ví dụ "EdgeTab" để lấy tab thật của trình duyệt
          "automation_id" – AutomationId, định danh ổn định nhất
          "type"          – control type chính xác: "TabItem", "Document", "Table", "Edit"…
          "pattern"       – phần tử có pattern đó: "grid", "scroll", "value", "toggle"…
        limit: số kết quả tối đa.
        include_offscreen: True để lấy cả phần tử đang ẩn (menu chưa mở, item ngoài viewport).
        within: id của một phần tử đã biết — chỉ tìm trong nhánh con của nó. Cần thiết với
            trình duyệt: tìm trong cả cửa sổ sẽ lẫn chrome của Edge (nút, thanh địa chỉ,
            bookmark) vào kết quả của trang web. Truyền id của Document để chỉ tìm trong trang.

    Kết quả khớp chính xác được xếp trước khớp một phần.
    """
    return _run(
        perceive.find,
        query=query,
        window=window,
        by=by,
        limit=limit,
        include_offscreen=include_offscreen,
        within=within,
    )


@mcp.tool(annotations=READ_ONLY)
def landmark_capture(window: str = "focused") -> str:
    """Quét một lần và ghi toạ độ mọi phần tử có tên của ứng dụng đó, để lần sau trỏ nhanh.

    Dùng cho ứng dụng nặng mà bạn làm việc thường xuyên. Đo trên Revit 2027 có model:
    quét toàn cây mất 16 giây và ngay cả FindAll đã lọc control type vẫn mất 6 giây, trong
    khi ElementFromPoint chỉ tốn ~2 ms. Trả 16 giây một lần, đổi lấy mọi lần trỏ sau đó
    gần như tức thì.

    Chạy lại khi giao diện đổi đáng kể (đổi tab ribbon, bật/tắt panel, đổi kích thước cửa sổ).
    """

    def work() -> str:
        target = perceive.resolve_window(window)
        data = landmarks.capture(target)
        return (
            f"đã ghi {len(data['entries'])} điểm neo cho {landmarks.app_key(target)} "
            f"(lần quét này mất {data['scan_ms']} ms). Từ giờ dùng landmark_find()."
        )

    return _run(work, timeout=180)


@mcp.tool(annotations=READ_ONLY)
def landmark_find(
    query: str, window: str = "focused", type: str | None = None, activate: bool = False
) -> str:
    """Trỏ tới một phần tử bằng điểm neo đã lưu — ~2 ms thay vì vài giây quét cây.

    Luôn kiểm chứng lại danh tính bằng ElementFromPoint trước khi trả về, nên điểm neo cũ
    sẽ báo hỏng chứ không trả về nhầm phần tử. Khi đó dùng find() rồi landmark_capture()
    để cập nhật.

    Tham số:
        query: tên phần tử (khớp chính xác được ưu tiên, sau đó mới tới khớp một phần).
        type:  lọc thêm theo control type, ví dụ "Text", "Button".
        activate: đưa cửa sổ đích lên trên trước khi giải. Cần khi cửa sổ đang bị che —
            điểm neo là toạ độ màn hình nên ElementFromPoint sẽ trả về cửa sổ nằm trên.
    """

    def work() -> str:
        target = perceive.resolve_window(window)
        element, note = landmarks.resolve(target, query, type, activate=activate)
        if element is None:
            return f"KHÔNG GIẢI ĐƯỢC: {note}"
        return "\n".join([note, "# id|type|name|state|patterns", perceive.describe(element)])

    return _run(work)


@mcp.tool(annotations=READ_ONLY)
def landmark_status(window: str = "focused") -> str:
    """Cho biết ứng dụng này đã có bao nhiêu điểm neo, chụp lúc nào, và cửa sổ có bị dịch chuyển không."""

    def work() -> str:
        return landmarks.summary(perceive.resolve_window(window))

    return _run(work)


@mcp.tool(annotations=READ_ONLY)
def describe_at(x: int, y: int) -> str:
    """Cho biết phần tử nào nằm dưới một điểm màn hình (~2ms).

    Dùng khi người dùng nói "cái nút chỗ này" và bạn đã biết toạ độ, hoặc để kiểm tra
    chéo một phần tử. Không chụp ảnh.
    """
    return _run(perceive.describe_at, x, y)


@mcp.tool(annotations=READ_ONLY)
def read_text(id: int, max_chars: int = 8000) -> str:
    """Đọc nội dung văn bản của một phần tử qua TextPattern — thay cho OCR.

    Trả về đúng ký tự ứng dụng đang giữ, nên tiếng Việt có dấu luôn chính xác.
    """

    def work() -> str:
        return text.read_text(REGISTRY.get(id), max_chars=max_chars)

    return _run(work)


@mcp.tool(annotations=READ_ONLY)
def read_table(id: int, start_row: int = 0, max_rows: int = 50) -> str:
    """Đọc một bảng/lưới qua GridPattern, trả về các hàng phân tách bằng dấu `|`.

    Dùng start_row để phân trang bảng dài. Khi start_row > 0, hàng 0 vẫn được kèm theo
    vì ở nhiều lưới đó là hàng tiêu đề cột.

    Cảnh báo về lưới ảo hoá: RowCount là số logic của ứng dụng, không phải số hàng đang
    có dữ liệu. Lưới của SAP khai báo 10000 hàng nhưng chỉ ~11 hàng đang render là có
    nội dung. Kết quả sẽ nói rõ bao nhiêu hàng đọc được là rỗng.
    """

    def work() -> str:
        return text.read_table(REGISTRY.get(id), start_row=start_row, max_rows=max_rows)

    return _run(work)


@mcp.tool(annotations=MUTATING)
def act(id: int, action: str, value: str | None = None) -> str:
    """Tác động lên một phần tử bằng control pattern của nó, không phải bằng toạ độ.

    Ưu tiên control pattern (bậc 1): không cần cửa sổ ở foreground, không cướp chuột
    của người dùng, không có lỗi "click trượt". Chỉ khi provider không hỗ trợ thì mới
    tụt dần xuống focus+phím rồi chuột thật. Kết quả trả về luôn ghi rõ đã dùng bậc nào.

    Tham số:
        id: lấy từ observe().
        action: click | double_click | right_click | set_value | type | toggle | select
                | expand | collapse | scroll | scroll_into_view | set_number | focus
                | click_physical | close | restore | minimize | maximize
        value: - set_value/type: nội dung text
               - scroll: "up"/"down"/"left"/"right" hoặc phần trăm ví dụ "50"
               - set_number: số cho slider/spinner

    Dùng set_value thay cho type khi có thể: nó ghi thẳng qua ValuePattern, tức thì và
    không cần focus.
    """

    def work() -> str:
        return actions.act(REGISTRY.get(id), action, value)

    return _run(work)


@mcp.tool(annotations=READ_ONLY)
def notifications(
    limit: int = 20, app: str | None = None, kind: str = "toast", since_hours: float | None = None
) -> str:
    """Đọc thông báo Windows gần đây, mới nhất trước.

    Đọc thẳng kho SQLite của Notification Center — chỉ đọc, **không mở panel thông báo**,
    không đụng gì tới màn hình của người dùng.

    Toast biến mất rất nhanh: Windows xoá khi người dùng gạt đi hoặc khi hết hạn. Đo được
    trong lúc phát triển: kho tụt từ 19 xuống 13 bản ghi, toast từ 4 về 0, chỉ trong vài
    phút. "Không có gì" thường nghĩa là chưa có gì gần đây, không phải tool hỏng — thử
    kind="all" để thấy cả tile và badge vốn trụ lâu hơn.

    Riêng tư: thông báo chứa nội dung cá nhân thật (tin nhắn, email). Chỉ dùng khi người
    dùng yêu cầu.

    Tham số:
        limit: số dòng tối đa.
        app: lọc theo tên app hoặc AUMID, không phân biệt hoa thường.
        kind: "toast" (mặc định) · "tile" · "badge" · "all".
        since_hours: chỉ lấy thông báo trong ngần ấy giờ gần đây.
    """

    def work() -> str:
        return notifications_module.read(
            limit=limit, app=app, kind=kind, since_hours=since_hours
        )

    return _run(work, timeout=30)


@mcp.tool(annotations=READ_ONLY)
def screenshot(tried: str, window: str = "focused") -> str:
    """LỰA CHỌN CUỐI CÙNG. Chụp ảnh một cửa sổ, lưu ra file PNG, trả về đường dẫn.

    Chỉ dùng khi cả hai bậc trên đều đã bó tay:
      1. MCP riêng của ứng dụng (revit-mcp, Excel-MCP, Navisworks, Outlook…)
      2. UIA — observe(), find(), read_text(), read_table()

    Bậc 1 và 2 cho biết trạng thái thật (enabled, on/off, giá trị ô nhập) mà ảnh không
    có, và rẻ hơn hàng nghìn token mỗi lần nhìn. Ảnh chỉ đáng dùng với bề mặt vẽ trên
    canvas — viewport 3D của Revit, canvas AutoCAD, lưới Excel Online, game — nơi thật
    sự không còn gì để đọc.

    Tham số:
        tried: BẮT BUỘC. Nêu cụ thể đã thử gì và thất bại ra sao. Không phải thủ tục
            hành chính — nó buộc dừng lại một nhịp để tự hỏi đã thử API và UIA chưa,
            và để lại dấu vết vì sao lần này phải dùng ảnh. Khai qua loa sẽ bị từ chối.
        window: "focused" (mặc định), "desktop" cho toàn màn hình, hwnd, hoặc tiêu đề.

    Trả về đường dẫn file; dùng tool Read trên đường dẫn đó để xem ảnh.
    """

    def work() -> str:
        target = None if window == "desktop" else perceive.resolve_window(window)
        return screenshot_module.capture(target, tried)

    return _run(work, timeout=60)


@mcp.tool(annotations=MUTATING)
def press_key(combo: str) -> str:
    """Gửi một tổ hợp phím tới cửa sổ đang focus, ví dụ "enter", "ctrl+s", "alt+f4".

    Dùng cho phím tắt toàn cục. Để nhập text vào một ô cụ thể, dùng act(set_value)
    vì nó không phụ thuộc focus.
    """
    from . import rawinput

    def work() -> str:
        rawinput.press_key(combo)
        return f"OK: đã nhấn {combo}"

    return _run(work)
