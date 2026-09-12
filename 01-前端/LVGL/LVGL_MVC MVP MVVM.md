# LVGL 中 MVC、MVP、MVVM：以开关控制统一边界

> 目标：以 LVGL 设置页的“屏幕开关”为例，说明 MVC、MVP、MVVM 的区别，并统一三种架构与 `Msg`、`Device` 的边界。重点是看清一次控制中：意图在哪里产生、真实状态在哪里更新、设备消息由谁发送、页面由谁刷新。

## 1. 统一总边界

MVC、MVP、MVVM 都是**应用 UI 架构模式**，只决定 View 到 Model 之间由谁协调。`Msg` 与 `Device` 不属于这三种模式，而是三者共同依赖的通信与设备边界。

```text
┌──────────── 应用 UI 架构层 ────────────┐      ┌──── 通信 / 设备边界 ────┐
│ MVC：View / Controller / Model         │      │ Msg  →  Device          │
│ MVP：View / Presenter  / Model         │ ───► │ Device →  Msg           │
│ MVVM：View / Binder / ViewModel / Model│ ◄─── │                          │
└────────────────────────────────────────┘      └──────────────────────────┘
```

三种模式共同遵守：

1. **View 只表达用户意图和展示状态。** `lv_switch` 的选中状态不是业务真相。
2. **Model 是业务状态唯一来源。** 只有收到 Device 的确认上报后，才修改 `enabled`。
3. **Msg 是消息适配层。** 它把“打开屏幕”的应用意图编码为设备消息、发送出去；收到设备上报后，再转交 Model。Msg 不决定页面展示，也不保存业务真相。
4. **Device 是设备边界。** 它接收指令、执行，并异步上报成功、失败或当前状态。

## 2. 各模块只做什么

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| View | 创建 LVGL 控件；把点击转成 `wanted`；按快照渲染开关、loading、错误 | 保存真实设备状态；组装设备消息 |
| Controller / Presenter / ViewModel | 各自模式中的应用协调 | 直接操作 Device；替代 Model 保存设备真相 |
| Model | 保存 `enabled`、`setting`、`last_error`；应用设备上报；通知订阅者 | 保存 `lv_obj_t *`；编码协议字段 |
| Msg | 将应用意图转换成设备消息；发送；接收设备回包；投递上报事件 | 决定开关展示；写业务规则 |
| Device | 接收命令、执行硬件/系统动作、上报执行结果或状态变化 | 理解 UI 页面、MVC/MVP/MVVM |

建议目录：

```text
screen/
  view/                 LVGL 页面、控件和事件适配
  mvc/ | mvp/ | mvvm/   三种模式之一的应用协调代码
  model/                设备确认状态、请求状态、订阅
  msg/                  应用意图 <-> 设备消息的转换与收发
device/                 设备侧命令处理与状态上报（若在同一仓库）
```

## 3. 统一的开关状态模型

以下状态模型被 MVC、MVP、MVVM 共用。它归 Model 所有，不属于 Msg，也不属于 LVGL 控件。

```c
/* 位置：screen/model/screen_model.h
 * 层级：Model
 */
typedef struct {
  bool enabled;       /* Device 最后一次已确认的真实状态 */
  bool setting;       /* 当前是否存在未完成的控制请求 */
  int  last_error;    /* 最近一次请求错误；0 表示无错误 */
} screen_model_t;
```

| 时刻 | `enabled` | `setting` | View 应展示 |
| --- | --- | --- | --- |
| 初始，设备已确认关闭 | `false` | `false` | 关闭，可点击 |
| 用户要求打开，尚未确认 | `false` | `true` | 仍按关闭渲染，禁用并显示 loading |
| Device 成功确认打开 | `true` | `false` | 打开，可点击 |
| Device 失败/超时 | `false` | `false` | 关闭，显示错误 |

`wanted=true` 只是一次请求的**意图**，可由协调层或 Msg 调用参数短暂携带；不能把它当作 Model 的已确认状态。

## 4. Msg 与 Device 的固定数据流

无论采用哪种 UI 架构，穿过 Msg 与 Device 的链路都相同：

```text
应用协调层
  -> Msg::send_set_screen(wanted)
       -> 将 wanted=ON 编码为设备命令，例如 { cmd: "set_screen", enabled: true }
       -> 发送给 Device

Device
  -> 接收命令并执行
  -> 异步上报 { type: "screen_report", enabled: true, error: 0 }

Msg
  -> 解码上报，投递到 UI 线程
  -> Model::apply_device_report(enabled, error)
```

**Msg 层：`screen/msg/screen_msg.c`**。不包含 `lv_obj_t`，也不直接调用 View。

```c
/* 出站：应用层表达意图，Msg 转为设备消息。 */
void screen_msg_send_set_screen(bool wanted)
{
  device_message_t msg = {
    .cmd = "set_screen",
    .enabled = wanted,
  };
  device_bus_send(&msg);
}

/* 入站：Msg 只解析、投递；由 Model 写入业务状态。 */
void screen_msg_on_device_report(const device_message_t *msg)
{
  screen_report_t report = decode_screen_report(msg);
  ui_post_apply_screen_report(report);  /* 在 LVGL UI 线程中调用 Model */
}
```

**Device 侧：`device/screen_command_handler.c`**。设备只处理协议命令及执行结果。

```c
void device_on_set_screen(const device_message_t *msg)
{
  int error = hardware_set_screen(msg->enabled);
  device_bus_report_screen(msg->enabled, error);
}
```

**Model 层：`screen/model/screen_model.c`**。Model 是唯一写入 `enabled/setting/error` 的位置。

```c
void screen_model_begin_request(screen_model_t *m)
{
  m->setting = true;
  m->last_error = 0;
  screen_model_notify(m);
}

void screen_model_apply_device_report(screen_model_t *m, bool enabled, int error)
{
  m->setting = false;
  if (error == 0) m->enabled = enabled;  /* 仅 Device 确认后更新 */
  m->last_error = error;
  screen_model_notify(m);
}
```

## 5. MVC：Controller 同时协调 Model 与 View

### 5.1 模块划分

```text
View --用户意图--> Controller --开始请求--> Model
                         │                    │
                         └--控制意图--> Msg -> Device

Device -> Msg --设备上报--> Model --状态通知--> Controller --render--> View
```

- **View**：注册 `LV_EVENT_VALUE_CHANGED`，把 `wanted` 交给 Controller；按 Model 快照绘制。
- **Controller**：接收 View 意图，调用 Model 开始请求与 Msg 发送命令；订阅 Model 后调用 View 渲染。
- **Model / Msg / Device**：严格使用第 3、4 节的公共职责，不因 MVC 改变。

### 5.2 一次打开开关的流转

```text
1. View: 用户点击 LVGL 开关，产生 wanted=ON。
2. Controller: 调用 Model::begin_request()。
3. Model: enabled 仍为 OFF，setting=true；通知 Controller。
4. Controller: 调用 View::render()，页面显示 OFF + loading；调用 Msg::send_set_screen(ON)。
5. Msg -> Device: 命令发送并执行。
6. Device -> Msg -> Model: 异步上报成功 enabled=ON。
7. Model: enabled=ON，setting=false；通知 Controller。
8. Controller: 调用 View::render()，页面显示 ON。
```

### 5.3 伪代码位置

**View：`screen/view/screen_view_lvgl.c`**

```c
static void on_switch_changed(lv_event_t *e)
{
  screen_view_t *v = lv_event_get_user_data(e);
  bool wanted = lv_obj_has_state(v->sw, LV_STATE_CHECKED);
  v->on_toggle(v->listener_ctx, wanted);  /* 只上报意图 */
}

void screen_view_render(screen_view_t *v, const screen_model_t *m)
{
  set_switch_checked(v->sw, m->enabled);
  set_switch_enabled(v->sw, !m->setting);
  lv_label_set_text(v->hint, m->last_error ? "设置失败" : "");
}
```

**Controller：`screen/mvc/screen_controller.c`**

```c
static void controller_on_toggle(void *ctx, bool wanted)
{
  screen_controller_t *c = ctx;
  screen_model_begin_request(c->model);
  screen_msg_send_set_screen(wanted);
}

static void controller_on_model_changed(void *ctx, const screen_model_t *m)
{
  screen_controller_t *c = ctx;
  screen_view_render(c->view, m);
}
```

MVC 的重点：Controller 同时知道 Model 与具体 View，简单直接，但页面增长后容易变大。

## 6. MVP：Presenter 通过 View 接口驱动展示

### 6.1 模块划分

```text
LVGL View --用户意图--> Presenter --开始请求--> Model
      ▲                       │                    │
      │                       └--控制意图--> Msg -> Device
      │
View 接口 <--show_state()-- Presenter <--状态通知-- Model <--设备上报-- Msg <- Device
```

- **LVGL View**：实现 View 接口；内部操作 `lv_obj_t`，但 Presenter 看不到这些控件。
- **Presenter**：接收 View 意图，调用 Model 与 Msg；收到 Model 快照后调用 `show_state()` / `show_error()`。
- **Model / Msg / Device**：职责与 MVC 完全相同。

### 6.2 一次打开开关的流转

```text
1. LVGL View: 用户点击，调用 Presenter::on_toggle(ON)。
2. Presenter: 调用 Model::begin_request()，再调用 Msg::send_set_screen(ON)。
3. Model: setting=true，通知 Presenter。
4. Presenter: 调用 View 接口 show_state(OFF, 请求中)；LVGL View 禁用开关并显示 loading。
5. Device 成功上报，经 Msg 交给 Model。
6. Model: enabled=ON，setting=false，通知 Presenter。
7. Presenter: 调用 View 接口 show_state(ON, 空闲)；LVGL View 显示 ON。
```

### 6.3 伪代码位置

**View 接口：`screen/view/screen_view.h`**

```c
typedef struct screen_view {
  void (*show_state)(struct screen_view *v, bool enabled, bool setting);
  void (*show_error)(struct screen_view *v, const char *text);
} screen_view_t;
```

**Presenter：`screen/mvp/screen_presenter.c`**

```c
static void presenter_on_toggle(void *ctx, bool wanted)
{
  screen_presenter_t *p = ctx;
  screen_model_begin_request(p->model);
  screen_msg_send_set_screen(wanted);
}

static void presenter_on_model_changed(void *ctx, const screen_model_t *m)
{
  screen_presenter_t *p = ctx;
  p->view->show_state(p->view, m->enabled, m->setting);
  if (m->last_error) p->view->show_error(p->view, "设置失败");
}
```

MVP 的重点：Presenter 不持有 `lv_obj_t`，可用 Mock View 测试展示决策。

## 7. MVVM：ViewModel 投影状态，Binder 同步控件

### 7.1 模块划分

```text
View -> Binder -> ViewModel Command -> Model -> Msg -> Device
  ▲        ▲                          │              │
  └--------┴--- Binder < property --- ViewModel <- Model <- Msg <- Device
```

- **View**：创建 LVGL 控件并把用户事件交给 Binder；不直接改 Model。
- **Binder**：把控件事件转为 ViewModel Command；订阅属性变化并写回 LVGL 控件。
- **ViewModel**：把 Model 快照转换为 `toggle_checked`、`toggle_enabled`、`error_text` 等页面属性；不持有 `lv_obj_t`。
- **Model / Msg / Device**：职责与前两种模式完全相同。

### 7.2 一次打开开关的流转

```text
1. View: 用户点击开关，向 Binder 提供 wanted=ON。
2. Binder: 调用 ViewModel::set_screen_enabled(ON)。
3. ViewModel: 调用 Model::begin_request() 与 Msg::send_set_screen(ON)。
4. Model: setting=true；通知 ViewModel。
5. ViewModel: 更新 toggle_checked=OFF、toggle_enabled=false；发出 property_changed。
6. Binder: 禁用 LVGL 开关并显示 loading。
7. Device 成功上报，经 Msg 交给 Model；Model 更新 enabled=ON、setting=false。
8. ViewModel: 投影 toggle_checked=ON、toggle_enabled=true；发出 property_changed。
9. Binder: 更新 LVGL 开关为 ON。
```

### 7.3 伪代码位置

**ViewModel：`screen/mvvm/screen_view_model.c`**

```c
void screen_vm_set_screen_enabled(screen_vm_t *vm, bool wanted)
{
  screen_model_begin_request(vm->model);
  screen_msg_send_set_screen(wanted);
}

void screen_vm_on_model_changed(screen_vm_t *vm, const screen_model_t *m)
{
  vm->toggle_checked = m->enabled;
  vm->toggle_enabled = !m->setting;
  vm->error_text = m->last_error ? "设置失败" : "";
  vm_notify_property_changed(vm, "screen_state");
}
```

**Binder：`screen/view/screen_lvgl_binder.c`**

```c
static void binder_on_property_changed(void *ctx, const char *name)
{
  screen_lvgl_binder_t *b = ctx;
  if (strcmp(name, "screen_state") != 0) return;
  b->rendering = true;  /* 程序化刷新不再触发 Command */
  set_switch_checked(b->sw, b->vm->toggle_checked);
  set_switch_enabled(b->sw, b->vm->toggle_enabled);
  lv_label_set_text(b->hint, b->vm->error_text);
  b->rendering = false;
}
```

MVVM 的重点：ViewModel 负责页面状态投影，Binder 负责属性到控件的最后一跳；两者都不替代 Msg 或 Device。

## 8. 三种模式：不变的部分与变化的部分

| 对比点 | MVC | MVP | MVVM |
| --- | --- | --- | --- |
| 用户意图先到 | Controller | Presenter | Binder → ViewModel Command |
| Model 变化后谁决定展示 | Controller | Presenter | ViewModel 投影属性，Binder 渲染 |
| 谁直接操作 LVGL | View 或 Controller | 仅 View 实现 | Binder / View |
| 对 Msg 的调用者 | Controller | Presenter | ViewModel |
| Msg 与 Device 的职责 | 三种模式完全一致 | 三种模式完全一致 | 三种模式完全一致 |

三种模式不能用“有没有 Msg / Device”来区分。真正的差别只有一处：**应用 UI 内部由 Controller、Presenter 还是 ViewModel/Binder 完成意图与展示的协调。**

## 9. 工程约束与面试要点

### 9.1 UI 线程

Device 上报往往来自通信线程。Msg 必须把解析后的纯数据投递到 LVGL UI 线程，再调用 Model；严禁 Msg 回调直接操作 `lv_switch`。

### 9.2 页面生命周期

View 销毁时，解除 Model 订阅、Binder 订阅或 Presenter/Controller 回调。Model 与 Msg 不能长期保存页面控件指针。

### 9.3 请求时序

连续点击时，Model 可保存 `request_id`。Msg 在设备消息中携带该 ID；Model 只应用当前请求对应的回包。失败时回渲染最后一次确认状态，而不是简单反转控件。

### 9.4 面试回答模板

**问：Msg 和 Model 的区别是什么？**

Msg 是协议/通信适配：把意图编码成设备消息并解析上报；Model 是领域状态：保存设备确认后的 `enabled`、请求状态和错误。Msg 不应直接修改控件，Model 不应拼协议包。

**问：MVC、MVP、MVVM 的共同链路是什么？**

共同链路是“View 产生意图 → 应用协调层开始请求 → Msg 发给 Device → Device 上报 → Msg 转交 Model → 应用协调层刷新 View”。区别只是应用协调层分别是 Controller、Presenter、ViewModel/Binder。

**问：为什么点击开关后不立即把 Model 的 enabled 改成 ON？**

点击只表示用户想打开；Device 可能失败、超时或被其他入口覆盖。应先设置 `setting=true`，等 Device 上报成功后再把 `enabled` 改为 ON。

## 10. 总结

一次可靠的设备开关控制，固定遵循下面的闭环：

```text
用户意图
  -> MVC / MVP / MVVM 的应用协调层
  -> Msg 编码并发送设备命令
  -> Device 执行并上报
  -> Msg 解析并转交 Model
  -> Model 更新已确认状态
  -> 对应架构层刷新 View
```

先守住 Model、Msg、Device 三者的职责边界，再选择 MVC、MVP 或 MVVM，架构才会清晰且可维护。
