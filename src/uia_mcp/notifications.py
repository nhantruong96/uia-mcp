"""Đọc thông báo Windows từ kho dữ liệu của Notification Center.

Ba đường có thể đi, và lý do chọn đường này:

* Mở Notification Center rồi đọc bằng UIA — phải bấm Win+N, tức **can thiệp vào màn
  hình của người dùng** chỉ để đọc. Và chỉ thấy những gì đang hiển thị.
* WinRT ``UserNotificationListener`` — API chính thức, nhưng thêm phụ thuộc và cần
  người dùng cấp quyền riêng.
* **Đọc thẳng ``wpndatabase.db``** — SQLite, chỉ đọc, không đụng gì tới màn hình, và
  có cả lịch sử chứ không riêng thứ đang hiện. Không cần thư viện ngoài: ``sqlite3``
  nằm sẵn trong Python.

Lưu ý riêng tư: thông báo chứa nội dung cá nhân thật — tin nhắn, email, cuộc gọi. Tool
này đọc đúng những thứ đó. Chỉ dùng khi người dùng yêu cầu.

Lưu ý về tuổi thọ dữ liệu: **toast biến mất rất nhanh**. Đo trực tiếp trong lúc viết
module này: kho từ 19 bản ghi (4 toast) xuống 13 bản ghi (0 toast) chỉ trong vài phút,
vì Windows xoá toast khi người dùng gạt đi hoặc khi nó hết hạn. Còn ``tile`` và ``badge``
thì trụ lâu hơn. Vậy nên "không thấy gì" ở đây thường có nghĩa là *chưa có gì gần đây*,
không phải là tool hỏng.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Microsoft"
    / "Windows"
    / "Notifications"
    / "wpndatabase.db"
)

#: FILETIME đếm số khoảng 100 nano-giây kể từ 1601-01-01 UTC.
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

KINDS = ("toast", "tile", "badge")


class NoNotificationStore(RuntimeError):
    """Không tìm thấy hoặc không đọc được kho thông báo."""


def _snapshot() -> Path:
    """Chép kho ra thư mục tạm rồi mới đọc.

    Windows đang giữ file này, và nó chạy ở chế độ WAL — chép mỗi ``.db`` mà bỏ
    ``-wal`` sẽ thiếu đúng những thông báo mới nhất, tức là thiếu thứ ta cần nhất.
    """
    if not DB_PATH.exists():
        raise NoNotificationStore(f"không thấy {DB_PATH}")
    target = Path(tempfile.gettempdir()) / "uia-mcp-wpn.db"
    for suffix in ("", "-wal", "-shm"):
        source = DB_PATH.with_name(DB_PATH.name + suffix)
        if source.exists():
            try:
                shutil.copy2(source, target.with_name(target.name + suffix))
            except OSError as exc:
                if suffix == "":
                    raise NoNotificationStore(f"không chép được kho: {exc}") from None
    return target


def _when(filetime: int) -> datetime | None:
    try:
        return (FILETIME_EPOCH + timedelta(microseconds=int(filetime) / 10)).astimezone()
    except Exception:
        return None


def _app_name(primary_id: str | None, display_name: str | None) -> str:
    """Tên app dễ đọc. ``HandlerAssets`` hầu như không có DisplayName nên phải suy từ AUMID."""
    if display_name:
        return display_name
    if not primary_id:
        return "(không rõ)"
    # AUMID kiểu 'Claude_pzs8sxrjxfjjc!Claude' hoặc 'Microsoft.Todos_8wekyb3d8bbwe!App'
    package = primary_id.split("!", 1)[0]
    return package.split("_", 1)[0] or primary_id


def _texts(payload: bytes | str | None) -> list[str]:
    """Lấy các đoạn <text> trong toast XML."""
    if not payload:
        return []
    raw = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return [" ".join(raw.split())[:200]]
    # Tile chứa nhiều <binding>, mỗi cái cho một cỡ ô, và thường lặp lại y hệt nội dung.
    # Không khử trùng lặp thì mỗi thông báo tile hiện ra ba lần cùng một câu.
    seen: set[str] = set()
    out: list[str] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag != "text" or not node.text or not node.text.strip():
            continue
        text = " ".join(node.text.split())
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def read(limit: int = 20, app: str | None = None, kind: str = "toast", since_hours: float | None = None) -> str:
    """Đọc thông báo gần đây, mới nhất trước."""
    if kind != "all" and kind not in KINDS:
        raise ValueError(f"kind phải là 'all' hoặc một trong {list(KINDS)}")

    snapshot = _snapshot()
    connection = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT n.ArrivalTime, n.Type, h.PrimaryId, n.Payload,
                   (SELECT AssetValue FROM HandlerAssets a
                     WHERE a.HandlerId = n.HandlerId AND a.AssetKey = 'DisplayName')
            FROM Notification n
            LEFT JOIN NotificationHandler h ON h.RecordId = n.HandlerId
            ORDER BY n.ArrivalTime DESC
            """
        ).fetchall()
    finally:
        connection.close()

    cutoff = None
    if since_hours:
        cutoff = datetime.now(timezone.utc).astimezone() - timedelta(hours=since_hours)

    needle = app.casefold() if app else None
    lines = ["# thời gian|app|loại|nội dung"]
    shown = 0
    for arrival, kind_value, primary_id, payload, display_name in rows:
        if kind != "all" and kind_value != kind:
            continue
        name = _app_name(primary_id, display_name)
        if needle and needle not in name.casefold() and needle not in str(primary_id or "").casefold():
            continue
        moment = _when(arrival)
        if cutoff and moment and moment < cutoff:
            continue
        body = " · ".join(_texts(payload)) or "(không có nội dung text)"
        stamp = moment.strftime("%Y-%m-%d %H:%M") if moment else "?"
        lines.append(f"{stamp}|{name}|{kind_value}|{body[:300]}")
        shown += 1
        if shown >= limit:
            break

    if shown == 0:
        lines.append(
            f"(không có thông báo nào khớp — kho có {len(rows)} bản ghi. Windows tự dọn "
            f"thông báo cũ, nên lịch sử ở đây ngắn chứ không đầy đủ.)"
        )
    return "\n".join(lines)
