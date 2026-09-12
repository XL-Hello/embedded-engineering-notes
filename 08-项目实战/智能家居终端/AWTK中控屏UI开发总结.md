# 智能中控屏 UI 项目开发流程与经验总结

## 项目概述

本项目基于致远电子开源前端框架 **AWTK** 开发，运行于 SoC 大核，面向智能中控屏提供完整的设置页 UI 与交互能力。项目覆盖从产品需求、视觉设计到 UI 业务逻辑落地的前端开发工作。

## 功能产出

负责智能中控屏设置页的整体 UI 及相关业务开发，主要包括：

Wi-Fi、账户绑定、显示、音量、语音、闹钟、系统更新等

## 整体架构

前端采用 `UI → Manager → Msg` 的三级架构：

```text
UI 层        页面展示、控件交互与数据驱动的页面逻辑
  ↓
Manager 层   非 UI 业务编排、功能策略与业务状态管理
  ↓
Msg 层       消息通信、底层数据获取与外部模块数据依赖
```

- **UI 层**：负责页面渲染、控件状态、用户事件响应和展示逻辑；页面逻辑以数据驱动为核心。
- **Manager 层**：承载与页面展示无关的业务逻辑，对 UI 层提供统一的业务能力；其数据主要依赖 Msg 层。
- **Msg 层**：负责消息收发、数据同步及与底层或其他模块的通信。

这种分层使界面展示、业务处理和数据通信各司其职，降低模块耦合度，也便于后续功能扩展和问题定位。

## 开发流程

### 1. 理解需求与设计

以产品 PRD 和 UI 开发稿为输入，先梳理功能目标、使用流程、页面状态、异常分支和交互细节；再结合设计稿明确页面布局、控件规格、视觉状态及跳转关系，形成可实施的开发拆分。

### 2. 搭建静态页面

使用 XML 描述页面结构，完成页面布局、控件组合和基础视觉效果。针对控件的默认、选中、禁用、按下等状态配置相应样式，保证页面在不同交互状态下的表现一致。

### 3. 建立数据与行为模型

根据功能需求定义页面和业务所需的数据结构、事件回调及状态字段；对存在多种处理方式的功能，使用策略模式封装不同业务行为，避免在页面逻辑中堆积复杂条件判断。

### 4. 实现数据驱动的 UI 逻辑

通过观察者模式解耦 UI 与数据：数据变化时通知订阅页面更新，页面根据最新状态刷新控件显示、可用性和交互结果。UI 层不直接依赖底层数据实现，从而使页面逻辑更清晰、可维护。

### 5. 完善 Manager 与 Msg 协作

在 Manager 层实现非 UI 的业务逻辑和流程编排，并通过 Msg 层获取、更新或订阅所需数据。UI 层通过 Manager 使用业务能力，避免直接处理底层通信细节。

### 6. 联调与验证

围绕正常流程、状态切换、数据更新、异常返回和页面返回等场景进行联调，重点验证 UI 显示是否能够及时、准确地反映业务状态，以及各层之间的数据流是否闭环。

## 开发经验

1. **先统一需求理解，再进入编码。** 对 PRD、设计稿和交互状态进行前置梳理，可以减少返工，尤其适用于设置页这类状态较多、功能彼此关联的页面。
2. **静态页面与业务逻辑分阶段完成。** 先用 XML 固化布局和样式，再接入数据和事件，有助于将视觉问题与业务问题分开排查。
3. **坚持数据驱动 UI。** 页面仅关注“当前数据应呈现什么状态”，由观察者机制响应数据变化，能够降低 UI 与业务、通信模块之间的耦合。
4. **用策略模式管理可变行为。** 对同类功能下的不同处理规则进行封装，使业务扩展不必频繁修改页面主流程。
5. **严格遵循三级分层。** UI、Manager、Msg 的职责边界清晰后，功能复用、模块测试、问题定位和后续维护都会更高效。

## 总结

该项目的核心实践是：以 PRD 和设计稿为起点，使用 AWTK 的 XML 能力高效构建页面，通过数据驱动和观察者模式实现 UI 与数据解耦，并依托 `UI → Manager → Msg` 的三级架构完成设置页的业务闭环。该方法既保证了界面开发效率，也提升了项目的可维护性和扩展性。

---

# 深入设计与面试追问：以项目代码为依据

本章用于说明上述架构在工程中的实际落点，并明确区分两类内容：

- **当前实现**：可以在本仓库代码中直接追溯的行为；
- **建议方案**：当前代码未完整覆盖、但量产级嵌入式 UI 应采用的设计与优化。

这样既能如实说明项目现状，也能说明对风险、边界和演进方向的理解。

## 1. 以 Wi-Fi 为例说明 UI → Manager → Msg

### 1.1 当前实现的完整调用链

Wi-Fi 页面位于 `cardPage/systemSet/setWifi/dreUI_cardSetWifi.c`。其职责是创建列表、注册控件事件、保存当前页面所需的控件引用，并把用户意图交给 Manager；它不直接组装总线消息。

以“刷新热点列表”为例，链路如下：

```text
用户点击刷新图标
  └─ UI: on_wifi_refresh_click()
       ├─ click_start_animator()：启动刷新动画与 10 s 超时定时器
       └─ dreUI_mgSystemCtrl_wifiScan(serial)
            └─ Manager: dreUI_mgSystemCtrl_wifiScan()
                 └─ Msg: dreUI_msgCtrl_wifiScan(serial, true)
                      └─ dreUI_msgSendToSystem(..., "wifi_scan", {"cmd":"start"})

系统服务异步上报 wifiListReport
  └─ Msg: dreUI_msgServerRecvBus()
       ├─ 深拷贝总线消息
       └─ timer_add(timer_callback, ..., 5)：延后到 AWTK 事件循环处理
            └─ dreUI_msgRecv_wifiListReport()
                 └─ Manager: dreUI_mgSystemRecv_wifiListUpdate(serial, json)
                      └─ 调用已绑定卡片的 fun_wifi_list()
                           └─ UI: dreUI_showFunc_wifiList()
                                ├─ 停止刷新动画
                                ├─ 合并同 SSID 的热点，保留较强信号
                                └─ 创建/更新列表项
```

连接流程与之类似：`on_wifi_item_click()` 或密码页发起 `dreUI_mgSystemCtrl_wifiConnect()`，Msg 层发送 `wifi_connect`；收到 `wifiConnectReport` 后，`dreUI_msgRecv_wifiConnectReport()` 调用 `dreUI_mgSystemRecv_wifiConnectUpdate()`，最终由 `fun_wifi_connected` 更新已连接区域、信号图标和网络受限提示。

页面初始化 `dreUI_cardSetWifi_init()` 会创建列表、调用 `dreUI_cardSetWifi_bind_init()` 完成订阅；若当前未连接 Wi-Fi，会自动触发一次扫描。列表回调会缓存最近一次 `wifiList` JSON，并在连接 SSID 改变时据此重绘列表，避免每次连接状态变化都重新扫描。

### 1.2 Manager 不是中转层

单纯把 UI 调用转给 Msg、再把 Msg 回调转给 UI 的“Manager”没有架构价值。Manager 应是**领域状态的唯一写入者和业务规则的裁决者**：

| 职责 | Wi-Fi 中应承担的内容 |
| --- | --- |
| 状态 | 扫描状态、连接状态、当前 SSID/IP、热点快照、最近错误、请求代次 |
| 缓存 | 最近一次有效扫描结果与时间戳；页面重进时先展示缓存，再后台刷新 |
| 幂等 | 同一 SSID 已连接时不重复连接；扫描中再次点击应合并而非重复发包 |
| 规则 | 热点去重、按连接态/信号排序、忽略空 SSID、网络切换后的失效策略 |
| 协调 | 扫描、连接、忘记网络互斥；连接成功后刷新列表和首页网络状态 |
| 对外接口 | 向 UI 暴露状态快照和订阅接口，而不是暴露原始 JSON 或总线细节 |

当前代码已经具备部分雏形：Wi-Fi 卡片会对同 SSID 去重、保存最近列表，并维护 `connecting_in_progress`；Manager 以 `bindCardList` 保存订阅页面。但状态仍有一部分放在页面静态变量 `s_sub_widgets` 中，页面销毁后不利于复用和测试。演进方向是把业务状态移至 `wifi_manager_t`，页面只保留 widget 与 subscription handle。

建议的数据模型如下：

```c
typedef struct {
  uint32_t generation;          /* 每次扫描/连接递增 */
  uint32_t active_serial;
  wifi_state_t state;           /* IDLE/SCANNING/CONNECTING/CONNECTED/FAILED */
  uint64_t snapshot_ms;
  char connecting_ssid[64];
  wifi_list_t scan_cache;
  wifi_connection_t connection;
  wifi_error_t last_error;
} wifi_manager_t;
```

### 1.3 晚到、重复和离页消息如何处理

当前 Wi-Fi 页面用 `rand() & 0xFFFF` 生成 serial 并把回包直接交给 Manager；这可用于日志关联，但当前链路尚未显示对 serial 做“只接受当前请求”的过滤。因此不能把它描述为已完整解决晚到回包的机制。

建议采用“请求代次 + 业务键 + 页面订阅令牌”三层保护：

1. Manager 发请求时递增 `generation`，记录 `active_serial`、目标 SSID 和请求时间；每个请求携带 `requestId/context`。
2. 收包时先验证协议字段、`serial/requestId` 与 `generation`。扫描只应用最新代次；连接还须匹配目标 SSID。超时、取消、网络切换后使当前代次失效。
3. Manager 更新自己的缓存后，向**仍有效的订阅者**发通知。页面的订阅对象带 `alive` 标志或 generation；解绑后不再有该页面的回调。

重复上报需要幂等：对状态快照计算版本号/哈希；数据未变化则不通知。对于进度类消息，仅接受单调递增的百分比；对于状态迁移，只允许预定义的合法边，例如 `CONNECTING → CONNECTED/FAILED`，不允许旧的 `CONNECTING` 把已连接状态覆盖。

### 1.4 UI 线程约束

`widget_t`、窗口栈、动画和图片管理器均应只在 AWTK UI 线程访问。当前 `dreUI_msgServerRecvBus()` 已将总线消息深拷贝，并通过 `timer_add(..., 5)` 延后执行；这表明项目采用了“总线接收线程不直接操作 UI，交给 AWTK 事件循环”的策略。

若底层回调来自其他线程，建议统一封装 `ui_post(task)`：复制纯数据到堆对象，投递到 AWTK 的 `idle_add` 或线程安全事件队列；回到 UI 线程后先检查 Manager 的 generation 和订阅令牌，再修改 widget。严禁在后台线程直接调用 `widget_set_text_utf8`、`widget_destroy`、`window_open` 或图片管理器接口。

## 2. 订阅、解绑、批处理与生命周期

### 2.1 当前绑定机制

`dreUI_manage_bind()` 维护 Manager 的 `bindCardList`。若同一 `cardHdl` 已存在，当前实现不会重复插入，而是立即执行一次 `managerHdl->bind()` 刷新页面；新绑定也会立即刷新。Wi-Fi 页面在 `dreUI_cardSetWifi_bind_init()` 中保存 `_mgBindHdl`，而卡片 `deinit` 会停止动画、调用 `dreUI_manage_unbind()` 并清空句柄。

这体现了正确的生命周期原则：**先构建 widget，后订阅；先停 timer/animator，后解绑；最后交给窗口销毁**。页面关闭事件应是唯一的释放入口，避免“返回按钮释放一次、窗口关闭再释放一次”的双重释放。

推荐的页面资源结构：

```text
page_create
  → create widgets
  → create page_ctx { alive=true, generation++, subscription }
  → manager_subscribe(snapshot)
  → render(snapshot)

EVT_WINDOW_CLOSE / EVT_DESTROY
  → ctx.alive=false
  → cancel timers / idle tasks / animation
  → manager_unsubscribe(subscription)
  → clear widget pointers
  → free ctx
```

### 2.2 避免悬空指针、重复订阅、重复渲染和回调重入

- **悬空 `widget_t*`**：业务层不长期持有裸 widget 指针；页面上下文在 `EVT_DESTROY` 清空所有引用。异步回调只持有 subscription token，执行时检查 `alive` 和 `widget != NULL`。
- **重复订阅**：订阅键定义为 `(manager, card/page instance)`；重复 bind 返回既有 handle。解绑必须幂等：NULL 或已解绑 handle 直接返回成功。
- **重复渲染**：Manager 比较版本号/脏字段；页面只渲染变化字段。当前 Wi-Fi 列表采用“销毁后重建”，容易造成布局和内存抖动；建议按 BSSID/SSID 做 diff，复用未变化列表项。
- **回调重入**：在点击、动画和总线回调入口加 `in_flight` 或状态机门禁。比如扫描中点击刷新只重置超时/标记“需要再扫”，而不是立即并发发送多次扫描。

### 2.3 通知语义与批处理

项目的总线消息是异步进入 UI 循环的；Manager 对已绑定卡片的刷新调用通常发生在该 UI 线程中，因此单次回调的 widget 更新是同步执行的。需要避免的是连续消息造成的多次同步重绘。

推荐 Manager 使用“状态更新同步、UI 通知合并异步”的模型：

1. 每条消息先原子更新 Manager 快照并累积 `dirty_mask`；
2. 若本帧尚未安排刷新，则仅投递一个 `idle_add`；
3. idle 回调取得最终快照，一次性通知所有订阅者；
4. UI 按脏字段更新文本、可见性和列表，末尾只做一次 `widget_layout`。

这样一条 Wi-Fi 连接状态消息同时改变 SSID、IP、信号、受限状态和列表筛选时，不会出现中间态闪烁。

### 2.4 一次可复现的生命周期风险排查

当前代码中存在一个可作为真实排查案例的风险：`win_set.c` 的 `on_setList_click()` 创建栈变量 `dreUI_jumpSubPageParam_t param`，并把 `&param` 传给 `navigator_to_with_context()`；`win_setTemplate_init()` 随后读取该指针。由于当前导航实现会在 `navigator_to_with_context()` 内同步创建窗口并立即调用 init，所以通常可工作；但一旦导航改为 `idle_add`、动画后创建或跨线程投递，该指针在回调执行前已经失效，会形成悬空 ctx。

排查步骤可以是：

1. 在导航入口、窗口 init、窗口 close 打印 `ctx` 地址、页面名和 generation；开启 AddressSanitizer 或堆校验。
2. 人为将窗口初始化延迟到下一轮 idle，重复进入/退出设置子页，观察标题乱码、偶发崩溃或错误页面。
3. 修复为堆分配的 `page_param_t`，由目标页 `EVT_WINDOW_CLOSE` 统一释放；或让 navigator 拷贝上下文并明确析构函数。
4. 回归“连续点击、立即返回、页面销毁后回包、内存压力循环 100 次”，检查订阅数量、活动 timer 数和堆水位是否回到基线。

这类案例的核心不是只说“free 了内存”，而是明确**谁创建、谁拥有、何时释放、异步边界在哪里**。

## 3. 页面导航、ctx 与模态窗口

### 3.1 导航接口的适用场景

项目在 `common/navigator.c` 对 AWTK 窗口管理器作了封装。

| 接口 | 当前行为 | 适用场景 |
| --- | --- | --- |
| `navigator_to` | 打开目标窗口，不主动关闭当前窗口 | 首页→控制中心、设置→设置子页；希望返回时保留上页状态 |
| `navigator_replace` | 打开目标主窗口并关闭当前主窗口 | 启动页→首页、登录成功后进入主页；旧页不应回退到 |
| `navigator_switch_to` | 目标已存在则切换，可选择关闭当前页；不存在则打开 | 在保活的首页/控制中心间切换，避免重复创建 |
| `navigator_back` | 交给窗口管理器返回上一窗口 | 子页返回设置、控制中心上滑返回首页 |
| `navigator_back_to_home` | 清理回退路径直达主页 | 设置完成、异常恢复、需要统一回主页 |

接口选择本质取决于返回栈语义，而不是“哪个函数能跳过去”。推荐栈规则为：`首页 → 控制中心 → 设置 → 设置子页` 使用 `to/back`；启动页完成后使用 `replace`；语音浮层、确认框、OTA 提醒使用 dialog/popup，不作为主页面栈成员。

### 3.2 ctx 的所有权

`navigator_to_with_context()` 当前只传递裸 `void*`，未表达所有权。因此调用者和目标页必须约定：

- **同步只读参数**可由调用方在调用期间提供，但不得被目标页保存；
- **异步或跨页面存活参数**必须堆分配/引用计数，并定义唯一释放者；
- 最稳妥的接口是 `navigator_to_with_context(target, ctx, destroy_ctx)`，由窗口关闭或初始化失败路径统一调用析构。

绝不能把栈变量当作可能异步使用的 ctx；函数返回后栈空间可被覆盖。Wi-Fi 详情页的 `wifi_detail_info_t` 当前使用 `malloc` 后传递，也应检查其是否在目标页关闭和导航失败路径中恰好释放一次。

### 3.3 单例窗口的实际语义与风险

当前 navigator 发现同名窗口且 `single_instance=true` 时，会先 `window_manager_close_window_force()`，再重新 `window_open_and_close()`。因此这里的单例并非“复用已有窗口”，而是“保证同时只有一个实例，重新打开会重建”。

优点是避免旧事件监听和旧上下文残留；代价是滚动位置、编辑输入、局部缓存和动画状态丢失，并要求关闭钩子能完整解绑 timer、订阅和堆对象。若目标是无闪烁地回到已打开页面，应使用 `navigator_switch_to()`，同时为页面提供 `on_resume(snapshot)` 刷新逻辑，而不是依赖重建。

### 3.4 快速点击与模态窗口

快速连续点击可能在窗口尚未入栈时重复触发 `navigator_to`。建议对每个导航动作维护 `navigating` 标志或 200~300 ms 去抖；目标窗口已存在时先 switch，触发失败后复位。不要只用全局“禁用全部点击”，否则会误伤关机、紧急返回等操作。

`navigator_window_open_and_close()` 会把 dialog 且配置 `dialog_to_modal=true` 的窗口设为模态。模态窗口应：

- 独占输入和焦点，底层页面不响应点击；
- 底层 Manager 仍可更新缓存，但不应直接抢焦点、打开新弹窗或改变当前用户决策；
- 关闭时检查父窗口仍存在，再按最新快照刷新；
- 重要操作（OTA 安装、删除 Wi-Fi）要求按钮幂等，防止重复确认。

## 4. 异步状态机：Wi-Fi 与 OTA

### 4.1 统一状态模型

通用异步操作至少应有以下状态：

```text
IDLE → LOADING → SUCCESS
              ├→ RETRYABLE_FAILURE → LOADING
              └→ TERMINAL_FAILURE
```

Wi-Fi 可细化为 `IDLE / SCANNING / CONNECTING / CONNECTED / FAILED`；OTA 当前已有 `IDLE / CHECKING / HAS_UPDATE / DOWNLOADING / DOWNLOAD_DONE` 等状态，并为检查设置 15 秒超时。Manager 应是状态机唯一迁移入口；UI 根据状态映射 loading、按钮禁用、文案和 toast，不能自行猜测成功。

### 4.2 缓存、超时、取消、离页与网络切换

- **进入页面**：先展示带更新时间的缓存，缓存过期或用户刷新时后台请求；不可因无缓存就展示旧成功态。
- **超时**：取消请求代次并进入可重试失败；Wi-Fi 刷新动画必须停止。当前 Wi-Fi 页面有 10 秒动画兜底，OTA 检查有 15 秒状态超时，这是合理基础。
- **离页**：取消“页面观察”，但业务请求可继续；回包只更新 Manager 缓存，不触碰已销毁页面。只有明确属于该页面的短期请求才发送取消。
- **重试**：新请求生成新 requestId/generation，旧回包一律丢弃；采用有限次数指数退避，不能无限自动重试。
- **网络切换**：使依赖旧网络的请求失效，清除连接态或标为 stale；切换完成后重新查询权威状态。

### 4.3 requestId/context 与错误呈现

每次请求生成单调递增 `requestId`，协议中同时传 `context`（例如 `wifi:connect:<ssid>:<generation>`）。Manager 收包先校验 requestId/context、目标资源和状态机允许的前序状态；不匹配只记录日志并丢弃。不要以随机 16 位 serial 作为唯一长期关联键，存在碰撞、重启复用和语义不明确的问题。

错误应从底层错误码映射为统一 UI 语义：

| 错误类别 | UI 行为 | 重试 |
| --- | --- | --- |
| 超时、临时网络不可达 | toast + 保留重试按钮 | 可重试 |
| 密码错误、认证失败 | 定位到密码输入并提示 | 用户修正后重试 |
| 版本签名/校验失败 | 明确失败页、停止安装 | 不自动重试 |
| 存储空间不足/电量不足 | 展示前置条件 | 条件满足后重试 |

### 4.4 OTA 的一致性要求

OTA 安装涉及不可逆外部状态，UI 不能把“点击安装”当作“已安装”。应以底层权威状态驱动：检查结果、下载进度、校验通过、写入完成、重启请求、重启后的版本确认。断电重启后先读取持久化 OTA 状态/启动槽位和当前版本，再恢复 UI；若状态未知，展示“正在确认”而非成功。版本校验失败进入终态失败，清理下载任务并提供可诊断错误码。安装过程中的弹窗和倒计时也必须在页面销毁时停止 timer，且二次确认时再次校验当前 OTA 状态。

## 5. AWTK 输入事件与横切能力

### 5.1 事件顺序与返回值

项目在 `dreameUI_start()` 中把全局回调注册到窗口管理器：`EVT_POINTER_UP_BEFORE_CHILDREN` 先于子控件处理，`EVT_POINTER_UP` 用于后续拦截。可按如下模型理解：

```text
窗口管理器 BEFORE_CHILDREN 监听
  → 命中窗口/子控件的事件处理
  → 控件自身默认处理与普通监听
  → 窗口管理器普通监听/后置逻辑
```

- `RET_OK`：本监听器处理完成，但允许事件继续传递；
- `RET_STOP`：停止后续分发；
- 错误地返回 `RET_STOP` 会表现为按钮无响应、滑动失效、焦点不更新或点击音不触发；错误地返回 `RET_OK` 则可能造成“唤醒同时点击”“一个动作执行两次”。

### 5.2 为什么息屏首触必须前置拦截

项目的前置全局回调会先调用息屏模块判断用户活动；若结果为 `CONSUME` 就返回 `RET_STOP`。这是为了实现“第一触只唤醒，不执行控件动作”。若在控件点击后才判断，用户点“删除”“安装”等操作可能在亮屏瞬间被误执行，既是 UX 问题也是安全问题。

### 5.3 手势冲突处理

建议定义手势仲裁规则：

- Pointer down 仅记录起点和时间；移动距离超过阈值后把序列归属给 scroll/slide，不再触发 click；
- 长按达到阈值后标记 `long_press_fired`，Pointer up 不再发 click；
- 点击按 Pointer up 确认并做短时间去抖，网络请求则额外由状态机去重；
- 父容器获得滑动后向子控件发送 cancel，避免滑动结束又触发列表项点击。

按键音、息屏、全局 popup、无操作屏保属于横切能力：它们需要所有页面行为一致、具有统一优先级且便于审计，因此放在窗口管理器事件、Manager 或独立服务中，而不应复制到每个页面。当前项目的全局触摸音和息屏前置处理正是这一思路。

## 6. 性能、资源与可量化验证

### 6.1 各类开销

| 项目 | 主要成本 | 优化方向 |
| --- | --- | --- |
| XML 页面 | XML 解析、widget 创建、样式匹配、布局 | 预加载关键页；减少深层嵌套；避免每次进入全量重建 |
| 图片 | 文件读取、解码、RGB/显存缓存、缩放 | 使用目标分辨率资源；复用图标；预取下一页关键图；及时清理无引用缓存 |
| 字体 | 字库加载、字形栅格化、文本布局 | 控制字号/字重种类；缓存常用字形；避免高频改变长文本 |
| 动画 | 每帧布局/绘制、透明混合、CPU/GPU 带宽 | 只动画 transform/opacity；减少 `relayout`；不可见时停止 animator |

### 6.2 页面保活还是销毁

保活减少 XML 创建和首帧耗时，但增加常驻内存，也可能保留旧订阅和过期状态；销毁释放内存更彻底，但回到页面需重建和恢复。建议按页面类型分层：

- 首页、短时间频繁切换的控制中心：可保活，进入时按快照增量刷新；
- 设置子页、复杂详情页：返回即销毁，Manager 缓存恢复状态；
- 图片重、低频的 OTA/二维码页面：按需创建，关闭后释放大图与动画。

选择必须用数据验证：首帧时间、峰值内存、返回体验和稳定性，而非固定偏好。

### 6.3 动态卡片页与图片缓存

`dreUI_pageManager_updateCardPages()` 的当前策略是：卡片顺序变化时移除并重建卡片页；顺序不变时复用 page container、只销毁其子控件后重新渲染。它已经避免了不必要的整个 `slide_view` 重建，但仍可能因每次销毁子树造成闪烁和分配压力。

优化顺序应为：先比较页面 ID、顺序和数据版本；未变化不渲染；仅字段变化时更新 widget；只有模板类型改变才重建子树；批量变更放到下一帧提交并保留当前页索引/滚动位置。

控制中心进入设置页时会清除首页背景图，并调用 `image_manager_unload_unused(image_manager(), 0)` 释放未被引用的图片缓存。触发前必须确认当前展示窗口不再引用该资源；验证方式是在跳转前后记录图片缓存数量/内存、重复进入返回后检查是否有缺图或重复解码，并结合堆水位确认释放真实生效。

### 6.4 性能指标与门槛

在内存受限设备上，应在真机建立基线并持续采集：

- 堆：启动后、首页稳定、连续 100 次进出设置页、峰值与退出后回落值；退出后不回落通常意味着 timer、订阅、图片或 ctx 泄漏。
- 启动：进程启动到首帧、到首页可交互、到首次数据同步完成的耗时。
- 切页：点击到目标页首帧、完整可交互的 P50/P95；同时记录丢帧数。
- 帧率/帧时间：动画和滑动时的平均与 P95 帧时间，关注长帧而非只看平均 FPS。
- 稳定性：消息风暴、断网、低内存、反复旋转动画/进出页面下的崩溃率和 UI 线程卡顿。

门槛需由产品屏幕规格和硬件能力确定。一个可执行的例子是：关键交互 P95 首帧不超过 300 ms、滑动 P95 帧时间不超过 33 ms、100 次页面循环后堆回落与基线差小于约 1%、无活动订阅和定时器残留。具体数值应以目标 SoC、分辨率和产品体验目标校准。
