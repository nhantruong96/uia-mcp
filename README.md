# uia-mcp

MCP server điều khiển Windows qua cây trợ năng **UI Automation** — cùng API mà NVDA và
Narrator dùng để đọc màn hình cho người khiếm thị.

**Không tool nào ở đây chụp ảnh màn hình.** Model không nhìn pixel và không đoán toạ độ:
nó đọc một bảng ID, rồi tác động lên ID bằng control pattern của chính ứng dụng.

Mọi con số đo đạc trong tài liệu này đều lấy từ máy thật, không phải ước lượng.

---

## Cài đặt

```bash
git clone https://github.com/nhantruong96/uia-mcp
cd uia-mcp
uv venv
uv pip install -e .
```

Yêu cầu: Windows 10/11, Python ≥ 3.11.

Kiểm tra bằng bộ test tự mở và tự đóng Notepad của riêng nó:

```bash
.venv\Scripts\python.exe smoke_test.py
```

## Đăng ký với Claude Code

```bash
claude mcp add uia --scope user -- <đường-dẫn-repo>\.venv\Scripts\uia-mcp.exe
```

---

## Bộ tool

| Tool | Công dụng |
|---|---|
| `list_windows()` | Mọi cửa sổ top-level: hwnd, class, pid, tiêu đề, cái nào đang focus |
| `observe(window, filter, max_elements)` | Bảng `id\|type\|name\|state\|patterns` của một cửa sổ |
| `find(query, window, by, limit, include_offscreen, within)` | Tìm phần tử ở **bất kỳ độ sâu nào**, không bị `max_elements` cắt |
| `landmark_capture(window)` | Quét một lần, ghi toạ độ mọi phần tử có tên của app đó |
| `landmark_find(query, window, type, activate)` | Trỏ bằng điểm neo — mili giây thay vì giây |
| `landmark_status(window)` | Đã có bao nhiêu điểm neo, chụp lúc nào, cửa sổ có dịch chuyển không |
| `describe_at(x, y)` | Phần tử dưới một điểm màn hình (~2 ms) |
| `read_text(id, max_chars)` | Nội dung văn bản qua `TextPattern` — thay OCR |
| `read_table(id, start_row, max_rows)` | Bảng/lưới qua `GridPattern`, có phân trang |
| `act(id, action, value)` | Tác động qua control pattern, có thang fallback |
| `press_key(combo)` | Phím tắt toàn cục, ví dụ `ctrl+s` |

### `observe` trả về gì

```
window: 'Untitled - Notepad' hwnd=919222 class=Notepad pid=27820
# id|type|name|state|patterns
0|Document|Text editor|focused|value,scroll,text
3|TabItem|Untitled. Unmodified.|selected|select
5|Button|Add New Tab||invoke
6|MenuItem|File|collapsed|invoke,expand
11|Button|Bold (Ctrl+B)|off|toggle
```

`filter`: `interactive` (mặc định) · `text` (nội dung đọc được) · `table` (lưới/bảng — dùng
trước `read_table`) · `all` (mọi thứ đang hiển thị).

Cột `state` chứa đúng những thứ ảnh chụp màn hình không nói chắc được: `focused`,
`disabled`, `on`/`off`, `selected`, `expanded`/`collapsed`, giá trị thật của ô nhập,
phần trăm cuộn. Cột `patterns` cho biết phần tử chấp nhận hành động nào.

### `find` — khi `observe` không với tới

`observe` cắt theo thứ tự duyệt cây, nên thứ nằm sâu không bao giờ tới lượt. Đo trên máy
này: bảng thư Outlook là phần tử **196/325**, tab thật của Edge nằm dưới `EdgeTabStrip`.
Tăng `max_elements` chỉ tổ đổ cả cây vào context. `find` không bị giới hạn đó.

`by`:

| | |
|---|---|
| `auto` (mặc định) | khớp name, AutomationId hoặc ClassName |
| `name` · `automation_id` · `class` | chỉ trường đó |
| `type` | control type chính xác: `TabItem`, `Document`, `Table`, `Edit`… |
| `pattern` | phần tử có pattern đó: `grid`, `scroll`, `value`, `toggle`… |

```
find("EdgeTab", window=<edge>, by="class")
→ find('EdgeTab', by=class): 7 kết quả, 1 khớp chính xác (xếp đầu)
  0|TabItem|Product Development - Materials - SAP Business ByDesign…|selected|select
  5|Button|Close tab [Ctrl+W]||invoke          ← EdgeTabCloseButton, khớp tiền tố

find("grid", window=<outlook>, by="pattern")
→ 7|Table|Table View|scroll-v=1%|scroll,grid   ← rồi read_table(7)
```

Khớp chính xác luôn xếp trước khớp một phần, và header nói rõ có bao nhiêu cái chính xác —
tìm class `EdgeTab` cũng trúng `EdgeTabCloseButton`, `EdgeTabStrip`, nên cần biết tin dòng nào.

**`within=<id>`** thu phạm vi về một nhánh con. Với trình duyệt thì gần như bắt buộc: tìm
trong cả cửa sổ sẽ lẫn toàn bộ chrome của Edge vào kết quả của trang web. Đo trên SAP
Business ByDesign: `find("Button", by="type")` cho **38** kết quả trên cả cửa sổ, còn
`within=<id Document>` chỉ còn **19** — đúng các nút của trang.

### `read_table` — phân trang và lưới ảo hoá

`start_row` để đọc tiếp bảng dài; khi `start_row > 0`, hàng 0 vẫn được kèm theo vì ở nhiều
lưới đó là hàng tiêu đề cột.

**`RowCount` là số logic, không phải số hàng có dữ liệu.** Lưới của SAP khai báo `10000×6`
nhưng chỉ ~11 hàng đang render là có nội dung — phần còn lại rỗng hoàn toàn. Tool không im
lặng bỏ qua chúng, mà nói thẳng:

```
(3/3 hàng đọc được là rỗng — lưới ảo hoá, chỉ vùng đang render mới có dữ liệu.
 RowCount=10000 là số logic, không phải số hàng thật đang có.)
```

Muốn đọc sâu hơn thì phải `act(<id lưới>, "scroll", "down")` trước rồi đọc lại.

### Điểm neo — cho app nặng dùng thường xuyên

Thứ đắt là **duyệt cây**, không phải bộ lọc. Đo trên Revit 2027 có model mở:

| | |
|---|---:|
| Quét toàn cây (701 phần tử) | 16 325 ms |
| `FindAll` đã lọc theo control type | 6 245 ms |
| `find("Annotate")` | 11 477 ms |
| **`landmark_find("Annotate")`** | **36 ms** |
| `landmark_find("S100 - Foundation")` | 6 ms |

Trả một lần quét ~9–16 s, đổi lấy mọi lần trỏ sau đó nhanh gấp **~300 lần**.

```
landmark_capture(window="<hwnd Revit>")   → đã ghi 210 điểm neo (quét mất 9 280 ms)
landmark_find("Annotate", activate=True)  → giải bằng điểm neo tại (686, 57)   36 ms
```

Kho lưu ở `%LOCALAPPDATA%\uia-mcp\landmarks.json`, khoá theo **tên tiến trình** (`revit.exe`)
chứ không theo tiêu đề — tiêu đề Revit đổi theo model đang mở.

**Hai điều bắt buộc phải hiểu:**

*Điểm neo là toạ độ màn hình.* `ElementFromPoint` luôn trả về thứ **nằm trên cùng** tại điểm
đó, bất kể ta định nói tới cửa sổ nào. Nếu Revit bị Edge che, điểm neo của Revit sẽ trỏ vào
Edge. Vì vậy mặc định tool từ chối khi cửa sổ đích không ở trên cùng; truyền `activate=True`
để đưa nó lên trước.

*Mỗi lần dùng đều kiểm chứng lại danh tính.* Giải xong vẫn phải xác nhận phần tử dưới toạ độ
đó đúng là mục tiêu (hoặc con cháu của nó) rồi mới trả về. Điểm neo cũ bị **từ chối** kèm mô
tả thứ đang nằm ở đó, chứ không bao giờ trả về nhầm phần tử — click nhầm sang ứng dụng khác
là tai nạn đã xảy ra thật trong quá trình phát triển.

Chụp lại khi giao diện đổi đáng kể: đổi tab ribbon, bật/tắt panel, đổi kích thước cửa sổ.

### `act` — các action

`click` · `double_click` · `right_click` · `set_value` · `type` · `toggle` · `select` ·
`expand` · `collapse` · `scroll` · `scroll_into_view` · `set_number` · `focus` ·
`click_physical` · `close` · `restore` · `minimize` · `maximize`

`click_physical` bỏ qua mọi pattern và click chuột thật ngay — dùng khi provider nhận
pattern rồi báo thành công nhưng ứng dụng không phản ứng (đặc trưng của web view React).

Ưu tiên `set_value` hơn `type`: nó ghi thẳng qua `ValuePattern`, tức thì, và **không cần
cửa sổ ở foreground**.

---

## Thang fallback

Mỗi lời gọi `act` đi từ trên xuống và **báo lại nó dừng ở bậc nào**:

```
1. Control Pattern                    ← không cần foreground, không cướp chuột
2. LegacyIAccessible.DoDefaultAction()
3. SetFocus() + phím                  ← vẫn không cần toạ độ
4. Chuột thật tại BoundingRectangle   ← toạ độ từ UIA, không phải từ ảnh
```

```
OK: click qua InvokePattern.Invoke
OK: set_value qua ValuePattern.SetValue (không có synthetic input)
OK: click qua chuột tại BoundingRectangle (toạ độ 812,447 lấy từ BoundingRectangle)
      — đã bỏ qua: InvokePattern.Invoke: không áp dụng được; …
```

Dòng "đã bỏ qua" là dữ liệu đo được về chất lượng trợ năng của từng ứng dụng. Càng nhiều
lần phải tụt xuống bậc 4, ứng dụng đó càng khai báo UIA kém.

---

## Ba quyết định thiết kế đáng chú ý

**Một thread STA duy nhất.** UIA là COM và đòi hỏi STA. Nhiều thread cùng `CoInitialize`
rồi cùng chạm vào một cây UIA sẽ deadlock khi COM marshal qua lại giữa các apartment.
Mọi lời gọi ở đây đều đi qua `sta.STA`. Muốn song song thật thì phải nhiều **tiến trình**,
không phải nhiều thread.

**`CacheRequest.TreeScope = Element`.** `FindAllBuildCache(Subtree, …)` trả về N phần tử;
nếu cache request cũng chứa `Children`/`Subtree` thì provider dựng cache cho subtree của
*từng* phần tử — công việc bùng nổ bậc hai. Đo được: đặt đúng thì nhanh gấp ~2× so với đọc
live, đặt sai thì **chậm hơn 2–6×**.

**Không tin lời pattern — kiểm chứng hậu điều kiện.** Đo được hai lần, trên hai pattern
khác nhau:

- Notepad Win11 nhận `WindowPattern.SetWindowVisualState(Minimized)`, báo lại
  `CurrentWindowVisualState = 1`, trong khi `IsIconic()` vẫn `False` và cửa sổ vẫn hiện.
- Excel Online trong Edge nhận `ScrollPattern.Scroll(down)` và trả về thành công, trong
  khi `VerticalScrollPercent` không nhúc nhích.

Provider **nói dối**, và không có quy luật nào đoán trước được app nào nói dối ở pattern
nào. Với action có hậu điều kiện rẻ và đáng tin, mỗi bậc phải tự chứng minh — Win32
`IsIconic`/`IsZoomed` cho cửa sổ, phần trăm trước/sau cho cuộn — không chứng minh được thì
coi như bậc đó hỏng và tụt tiếp (`ShowWindow`, lăn chuột). Báo "OK" khi không có gì xảy ra
là thứ tệ nhất một tool có thể làm với agent.

Hai chi tiết khiến việc kiểm chứng dễ tự lừa mình:
*chỉ so trục được yêu cầu* (dao động ngang từng làm một lệnh cuộn dọc bất động trông như
thành công), và *đừng làm tròn về số nguyên* (`0.0 → 0.4%` in ra `"0% → 0%"` thì báo cáo
tự mâu thuẫn với chữ OK của chính nó).

**Toạ độ cho chuột phải là toạ độ sống.** Các bậc bơm chuột đọc `BoundingRectangle` bằng
`live=True`, không dùng rect trong cache. Rect cache là ảnh chụp lúc `observe`, có thể đã
cũ hàng giây và phần tử đã dịch đi vì cuộn hay đổi layout — click theo nó chính là lỗi
"click trượt" mà cả thiết kế này sinh ra để loại bỏ.

**Cửa sổ minimize phải được nói ra.** Windows không render cửa sổ đã minimize, nên cây UI
của nó co lại chỉ còn khung — không có Document, không có nội dung. Trả về cây rỗng mà
không giải thích sẽ khiến agent kết luận nhầm "ứng dụng này không có UI" và đi sai hướng.
`observe` phát hiện `IsIconic` và cảnh báo; `act(id, "focus")` tự bung cửa sổ ra trước khi
focus, vì `SetFocus` trên cửa sổ minimize trả về *thành công* mà không khôi phục gì.

**Trạng thái chỉ đọc khi pattern tồn tại.** UIA trả về giá trị mặc định
(`ToggleState=indeterminate`, `RangeValue=0`, `IsReadOnly=True`) cho *mọi* phần tử kể cả
khi provider không hỗ trợ pattern đó. Báo cáo nguyên xi sẽ dán nhãn sai lên gần như toàn
bộ cây — mà trạng thái sai còn tệ hơn không có trạng thái.

---

## Giới hạn đã biết

| Vấn đề | Xử lý |
|---|---|
| **Chrome/Edge/Electron/VS Code** có thể chỉ lộ title bar, nội dung web vô hình | Đo trên máy này: Edge **có** lộ đầy đủ cây web (đọc được toàn bộ text trang GitHub). Chromium bật provider khi có công cụ trợ năng yêu cầu, nên kết quả phụ thuộc từng máy — thử `observe(filter="text")` trước, chỉ khi rỗng mới cần `--force-renderer-accessibility` |
| **Cửa sổ minimize** trả về cây gần rỗng | `observe` cảnh báo `state=minimized`; gọi `act(<id Window>, "restore")` hoặc `act(..., "focus")` |
| **Java (Swing/AWT)** không có UIA | Cần Java Access Bridge — chưa làm, giai đoạn 3 |
| **Canvas / viewport 3D / game** chỉ là một `CustomControl` | UIA không cứu được. Dùng API riêng của app, hoặc vision |
| **Office web apps**: lưới Excel Online vẽ trên canvas — không `GridPattern`, `Document` báo `NoScroll` | Cây trợ năng vẫn đầy đủ (thanh công thức, Name Box, ribbon đều đọc được), nhưng bản thân lưới thì không. Muốn ô nào thì qua Name Box + formula bar, hoặc dùng Excel MCP trên file gốc |
| **Ribbon Revit — tab không có tên** | 22 phần tử `Tab`/`TabControl` đều rỗng `Name`. Không trỏ tới tab "Structure" hay "Add-Ins" bằng tên được. Nhưng **nhãn tab lại là `Text` riêng** ở dải y≈57 và có tên đầy đủ — tìm `Text` rồi click vào nó |
| **Ribbon Revit — panel không có phần tử con** | Panel ribbon là **leaf tuyệt đối**: 0 con ở cả Raw/Control/Content view, không pattern nào, `LegacyIAccessible.GetIAccessible()` trả `None`. Đúng với cả `Autodesk.Windows.RibbonPanel` (add-in) lẫn `UIFramework.RvtRibbonPanel` (native). **Ngoại lệ duy nhất: tab Architecture** — nó lộ ~47 lệnh có tên (Wall, Door, Window, Column…). Panel *có* lộ `rect`, nên chỉ còn cách click theo toạ độ và **kiểm chứng bằng hậu điều kiện thật** (ví dụ nút MCP Server của revit-mcp: kiểm tra cổng socket có LISTEN không) |
| ↳ *đã loại trừ bằng thực nghiệm* | Ngoại lệ Architecture **không** đến từ: pyRevit (ẩn Architecture → 0 ở mọi tab, không liên quan pyRevit) · thứ tự quét (đảo chiều vẫn 0/47/0/47) · tab nào mở đầu tiên (đặt Structure làm tab đầu → vẫn 0) · loại view (Sheet và Floor Plan đều như nhau) · model đang mở (tái hiện trên hai project khác nhau). Cơ chế thật vẫn chưa rõ. Kết luận thực dụng: **coi như lệnh ribbon không truy cập được**, vì ngoại lệ này phụ thuộc một tab mà người dùng tắt được bất cứ lúc nào |
| **App chạy admin** | Server phải cùng mức toàn vẹn, hoặc ký với `uiAccess=true` |
| Cửa sổ treo | `TransactionTimeout` 30s (chỉnh bằng `UIA_MCP_TRANSACTION_TIMEOUT_MS`) + timeout 20s ở tầng STA; sau đó server báo kẹt và cần khởi động lại. Đặt ngắn hơn sẽ hỏng trên app nặng: Revit cần 6–16s cho một lần duyệt subtree, ngưỡng 5s làm mọi truy vấn trả `UIA_E_TIMEOUT` dưới dạng COMError không thông điệp — rất dễ chẩn đoán nhầm thành "app treo" |
| Chưa có event-driven refresh | Mỗi `observe` là một lần quét lại — giai đoạn 2 |

---

## Nhắc lại thứ tự ưu tiên

UIA là **bậc 2**, không phải bậc 1. Trước khi dùng server này, hãy hỏi ứng dụng đó có API
không — Revit, AutoCAD, Navisworks, SAP2000, Excel, Graph, ACC đều đã có MCP riêng và
luôn nhanh hơn, tin cậy hơn việc đi qua GUI.

---

## Bố cục mã nguồn

| File | Vai trò |
|---|---|
| `sta.py` | Apartment STA dùng chung + timeout |
| `uia.py` | Bọc COM client: hằng số, điều kiện lọc, cache request, đọc property an toàn |
| `registry.py` | Bảng ID ổn định (`RuntimeId` → `AutomationId` → hash) |
| `perceive.py` | `list_windows`, `observe`, `describe_at` |
| `actions.py` | Thang fallback hành động |
| `text.py` | `read_text`, `read_table` |
| `rawinput.py` | `SendInput` — chỉ dùng ở các bậc fallback cuối |
| `server.py` | Định nghĩa tool MCP |
