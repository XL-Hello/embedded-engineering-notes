# 嵌入式前端-LVGL和AWTK介绍与对比
> 目标：这篇文档专注整理 LVGL 和 AWTK 两个嵌入式 GUI 框架的定位、架构、移植方式、对象模型、事件机制、布局、资源管理、线程模型、源码结构、关键取舍和选型建议。
>
> 说明：FrameBuffer、脏矩形、输入事件、线程安全等公共 GUI 基础知识已经在《嵌入式前端基础知识》一文中，本文只在涉及 LVGL、AWTK（因为作者仅涉及过这两个框架） 设计差异和工程落地差异时展开。

## 1. LVGL 和 AWTK 分别是什么

### 1.1 LVGL

**LVGL，全称 Light and Versatile Graphics Library，是一个用 C 写的轻量级嵌入式图形库。**

它的典型特点：

- 主要面向 MCU、MPU、RTOS、裸机、嵌入式 Linux 等场景。
- 用 C API 创建界面，近年来也支持 XML / Pro Editor 等工具链。
- 控件、样式、布局、事件、动画、输入设备、显示驱动适配都比较完整。
- 移植门槛低，只要能提供时间基准、显示刷新回调和输入读取回调，就可以跑起来。
- 社区活跃，资料多，常见 MCU、RTOS、Linux 平台都有较多示例。

直白理解：

> LVGL 更像一个轻量、通用、可移植的嵌入式 GUI 内核。你给它一块绘图缓冲和一个刷屏函数，它负责对象树、控件、事件、绘制和刷新调度。

### 1.2 AWTK

**AWTK，全称 Toolkit AnyWhere，是 ZLG 开源的跨平台嵌入式 GUI 引擎。**

它的典型特点：

- 面向嵌入式系统、RTOS、裸机、Linux、Windows、macOS、移动端、Web 等跨平台场景。
- 提供控件系统、窗口管理、事件机制、资源系统、主题、XML UI 描述、动画、输入法、多语言等能力。
- 配套 AWTK Designer，可视化设计 UI、预览界面、打包资源。
- 工程上强调 UI 描述文件、资源打包、主题和工具链。
- 除基础 GUI 能力外，还提供 MVVM 等更偏应用架构层的方案。

直白理解：

> AWTK 更像一个带完整工具链的跨平台 GUI 应用框架。它不仅提供绘制和控件，还更强调窗口、资源、主题、XML 描述、可视化设计和应用层组织方式。


## 2. LVGL 整体架构

### 2.1 LVGL 的分层理解

LVGL 可以按下面方式理解：

```text
应用层
  - 创建 screen、button、label、image
  - 绑定事件回调
  - 修改控件状态和样式

LVGL 核心层
  - 对象树 lv_obj
  - 控件 widget
  - 样式 style
  - 事件 event
  - 布局 layout
  - 定时器 timer
  - 动画 anim
  - 输入设备 indev

渲染层
  - draw unit
  - draw buffer
  - 软件渲染 / GPU 加速接口
  - 脏区域刷新

平台适配层
  - lv_tick
  - display flush callback
  - input read callback
  - memory / fs / log / OS port

硬件或系统层
  - LCD / FrameBuffer / DRM / SDL / SPI / MIPI
  - Touch / Encoder / Keypad
  - RTOS / Linux / Bare metal
```

### 2.2 LVGL 最小移植需要什么

一般要提供：

1. `lv_init()`：初始化 LVGL。
2. tick：提供毫秒级时间。
3. display：创建显示对象，设置分辨率和绘制缓冲。
4. flush 回调：把渲染好的像素写到屏幕。
5. input device：触摸、按键、编码器等输入设备读取回调。
6. 主循环：周期性调用 `lv_timer_handler()`。

典型流程：

```text
硬件初始化
  -> lv_init()
  -> 设置 tick
  -> 创建 display
  -> 设置 draw buffer
  -> 设置 flush_cb
  -> 创建 input device
  -> 创建 UI
  -> while(1) 调用 lv_timer_handler()
```

### 2.3 LVGL 对象模型

LVGL 的核心对象是 `lv_obj_t`。

所有控件都可以看成基于 `lv_obj_t` 扩展出来的对象：

- screen 是对象。
- button 是对象。
- label 是对象。
- image 是对象。
- slider、chart、list、table 也都是对象。

对象主要能力：

- 父子树。
- 坐标和尺寸。
- 样式和状态。
- 事件回调。
- layout。
- flag。
- 滚动。
- 绘制描述。

示例：

```c
lv_obj_t * btn = lv_button_create(lv_screen_active());
lv_obj_center(btn);

lv_obj_t * label = lv_label_create(btn);
lv_label_set_text(label, "OK");
lv_obj_center(label);
```

这段代码表示：

- 在当前 screen 上创建一个 button。
- 把 button 放到屏幕中央。
- 在 button 里面创建一个 label。
- label 是 button 的子对象。

### 2.4 LVGL 事件机制

LVGL 通过 `lv_obj_add_event_cb()` 给对象绑定事件回调。

常见事件：

- `LV_EVENT_PRESSED`
- `LV_EVENT_RELEASED`
- `LV_EVENT_CLICKED`
- `LV_EVENT_LONG_PRESSED`
- `LV_EVENT_VALUE_CHANGED`
- `LV_EVENT_DELETE`
- `LV_EVENT_DRAW_MAIN`

示例：

```c
static void btn_event_cb(lv_event_t * e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if(code == LV_EVENT_CLICKED) {
        /* 执行业务逻辑 */
    }
}

lv_obj_add_event_cb(btn, btn_event_cb, LV_EVENT_CLICKED, NULL);
```

理解要点：

- 事件绑定在对象上。
- 回调里可以拿到事件类型、目标对象、用户数据等。
- 一个对象可以有多个事件回调。
- 事件可能来自输入，也可能来自对象状态或生命周期变化。

### 2.5 LVGL 布局系统

LVGL 支持手动坐标，也支持布局。

常用方式：

- `lv_obj_set_pos()`：设置绝对位置。
- `lv_obj_set_size()`：设置尺寸。
- `lv_obj_align()`：对齐。
- Flex layout：类似 CSS Flexbox。
- Grid layout：类似 CSS Grid。

LVGL 布局适合：

- 工具栏。
- 参数设置页面。
- 列表项。
- 多分辨率适配。
- 横竖排列的控件组。

### 2.6 LVGL 资源管理

LVGL 常见资源：

- C 数组图片。
- 文件系统图片。
- 内置字体。
- 自定义字体。
- 样式对象。
- 主题。
- XML UI。

常见做法：

- 小 MCU 项目常把图片和字体转换成 C 数组，直接编译进固件。
- 嵌入式 Linux 项目可从文件系统读取图片、字体和配置。
- 字体要注意 CJK 字库大小，通常需要裁剪。
- 图片尽量转成和屏幕匹配的颜色格式。

### 2.7 LVGL 线程模型

LVGL 常见使用模型是单 UI 线程：

```text
UI task:
  while(1) {
      lv_timer_handler();
      delay(5ms);
  }
```

其他任务不要直接随意调用 LVGL API，推荐：

- 用消息队列通知 UI task。
- 用异步调用机制把函数投递到 UI 上下文。
- 在 RTOS 下对 LVGL 访问加统一互斥锁，但要控制锁范围。
- 中断里不要直接操作对象。

面试回答要点：

> LVGL 移植时最容易出问题的地方之一就是线程模型。业务线程直接改 UI，短期看能跑，压力一大就容易出现对象删除、刷新遍历、事件回调重入等问题。

### 2.8 LVGL 源码结构

LVGL 仓库常见目录可以这样理解：

| 目录 / 文件 | 作用 |
| --- | --- |
| `src/core` | 核心对象、事件、刷新、屏幕等核心逻辑 |
| `src/widgets` | 内置控件，比如 button、label、slider、image、chart |
| `src/draw` | 绘制模块，软件绘制和硬件加速相关抽象 |
| `src/display` | 显示设备抽象和刷新相关逻辑 |
| `src/indev` | 输入设备抽象，比如触摸、键盘、编码器 |
| `src/layouts` | Flex、Grid 等布局 |
| `src/misc` | 链表、内存、颜色、定时器、日志等基础工具 |
| `src/osal` | OS 抽象层 |
| `src/libs` | 第三方或辅助库集成 |
| `examples` | 示例代码 |
| `demos` | 演示工程 |
| `lv_conf_template.h` | 配置模板 |
| `lvgl.h` | 对外主头文件 |

学习源码时建议顺序：

1. 先看 `lv_init()` 和 `lv_timer_handler()`。
2. 再看 display 创建、buffer 设置、flush 调用。
3. 再看 `lv_obj_t` 和对象树。
4. 再看 event 分发。
5. 最后看 draw、layout、widget 细节。


## 3. AWTK 整体架构

### 3.1 AWTK 的分层理解

AWTK 可以按下面方式理解：

```text
应用层
  - 页面逻辑
  - 窗口切换
  - 控件事件处理
  - MVVM / 数据绑定

UI 描述和资源层
  - XML UI
  - theme
  - images
  - fonts
  - strings
  - packed resources

AWTK 核心层
  - widget
  - window
  - event
  - layout
  - animation
  - timer
  - main_loop
  - resource manager

平台适配层
  - LCD / canvas
  - input
  - file system
  - thread / mutex / time
  - native window or embedded port

系统或硬件层
  - Windows / Linux / RTOS / Bare metal
  - FrameBuffer / SDL / LCD / GPU / DMA2D
```

### 3.2 AWTK 工程启动流程

AWTK 项目通常包含：

- 初始化平台。
- 初始化 AWTK。
- 加载资源。
- 打开主窗口。
- 进入主循环。

典型理解：

```text
平台初始化
  -> AWTK 初始化
  -> 资源系统初始化
  -> 打开窗口 / 加载 UI 描述
  -> 绑定事件
  -> main_loop_run()
```

AWTK 比较强调“窗口”和“资源”的概念：

- 页面通常可以作为窗口或窗口内控件树组织。
- UI 可以通过 XML 描述。
- 图片、字体、主题、字符串等资源可以通过工具打包。
- AWTK Designer 可以参与 UI 设计和资源生成。

### 3.3 AWTK 对象模型

AWTK 的核心概念是 `widget_t`。

控件、窗口、容器都可以理解为 widget：

```text
window
 ├─ view / container
 │   ├─ button
 │   ├─ label
 │   └─ image
 └─ status_bar
```

widget 通常包含：

- 名称。
- 类型。
- 父子关系。
- 坐标和尺寸。
- 状态。
- 属性。
- 事件处理。
- 绘制函数。
- layout 信息。

AWTK 工程里经常会通过控件名称查找对象：

```text
window_open("main")
  -> widget_lookup(window, "ok_button", TRUE)
  -> widget_on(button, EVT_CLICK, on_ok_click, ctx)
```

这种方式适合 XML UI 和可视化设计工具配合使用。

### 3.4 AWTK 事件机制

AWTK 的事件机制围绕 `event_t` 和控件事件处理展开。

常见事件：

- 点击事件。
- 指针按下、移动、释放。
- 键盘事件。
- 值变化事件。
- 窗口打开、关闭事件。
- 定时器事件。
- 控件生命周期事件。

理解要点：

- 事件发给目标 widget。
- 应用可以给 widget 绑定事件处理函数。
- 控件内部也会处理自己的默认行为。
- 事件可以和 XML、名称查找、窗口生命周期结合使用。

### 3.5 AWTK 布局系统

AWTK 支持手动坐标，也支持通过 UI 描述文件和布局规则组织界面。

常见能力：

- XML 中描述控件层级。
- 控件属性中配置位置、尺寸、布局。
- 支持容器和自动排布。
- 适合配合 Designer 可视化调整。
- 适合项目里让 UI 结构和业务代码分离。

AWTK 的布局和资源系统往往一起使用：

```text
UI XML 描述界面结构
主题文件描述样式
资源包保存图片、字体、字符串
业务代码按控件名称绑定事件
```

### 3.6 AWTK 资源管理

AWTK 的资源体系是它比较重要的特点。

常见资源：

- XML UI 文件。
- 主题文件。
- 图片。
- 字体。
- 多语言字符串。
- 输入法资源。
- 打包后的二进制资源。

AWTK 适合这类工程模式：

1. UI 设计工具生成或维护界面描述。
2. 资源通过工具转换和打包。
3. 固件或应用运行时加载资源。
4. 业务代码通过名称查找控件并绑定逻辑。

这种方式的好处：

- UI 结构和业务代码分离。
- 设计师或 UI 工程师可以参与界面制作。
- 多页面、多主题、多语言项目更好管理。
- 资源可以统一打包，便于发布。

### 3.7 AWTK 线程模型

AWTK 也应按单 UI 主循环理解。

推荐方式：

- UI 操作集中在主循环线程。
- 后台任务通过消息、定时器或异步方式通知 UI。
- 不在事件回调里做耗时操作。
- 不在中断或后台线程直接删除、创建、修改 widget。

AWTK 里常见关注点：

- 窗口生命周期。
- widget 查找和使用时机。
- 资源加载是否在 UI 线程阻塞。
- 动画、定时器和事件回调是否造成重入问题。

### 3.8 AWTK 源码结构

AWTK 仓库常见目录可以这样理解：

| 目录 / 文件 | 作用 |
| --- | --- |
| `src` | AWTK 核心源码 |
| `src/base` | widget、event、window、main loop 等基础核心 |
| `src/widgets` | 常见控件 |
| `src/tkc` | 基础工具库，如字符串、容器、对象、平台抽象 |
| `src/lcd` | LCD、canvas、绘制相关抽象 |
| `src/platforms` | 平台适配相关代码 |
| `res` | 示例或默认资源 |
| `demos` | 示例应用 |
| `docs` | 文档 |
| `tools` / `scripts` | 工具和脚本 |
| `tests` | 测试 |
| `SConstruct` | SCons 构建入口 |
| `CMakeLists.txt` | CMake 构建入口 |

学习源码时建议顺序：

1. 先看示例程序如何初始化 AWTK。
2. 再看 `main_loop` 如何调度输入、事件、定时器和绘制。
3. 再看 `widget_t` 的结构和父子关系。
4. 再看窗口打开、关闭和资源加载。
5. 再看某个简单控件，比如 label 或 button。
6. 最后看 lcd/canvas、资源管理、平台适配。


## 4. LVGL 和 AWTK 的差异对比

### 4.1 定位差异

| 维度 | LVGL | AWTK |
| --- | --- | --- |
| 核心定位 | 轻量级嵌入式 GUI 库 | 跨平台嵌入式 GUI 引擎和应用框架 |
| 典型场景 | MCU、RTOS、裸机、嵌入式 Linux | RTOS、裸机、Linux、PC、移动端、Web 等 |
| 使用方式 | C API 创建 UI 为主，也支持 XML 工具链 | XML UI、资源包、Designer、代码绑定事件 |
| 工具链依赖 | 可以很轻，不依赖复杂工具 | 更强调工具链和资源工程 |
| 社区资料 | 国际社区活跃，资料丰富 | 中文资料和 ZLG 生态更友好 |

简单判断：

- 想快速在 MCU 上做一个轻量 UI，LVGL 更常见。
- 想做多页面、多资源、可视化设计、跨平台应用工程，AWTK 的整体框架感更强。

### 4.2 架构风格差异

| 维度 | LVGL | AWTK |
| --- | --- | --- |
| 核心对象 | `lv_obj_t` | `widget_t` |
| 页面组织 | screen + object tree | window + widget tree |
| UI 描述 | C API 常见，XML 能力逐步完善 | XML UI 和资源描述是重要工作流 |
| 样式系统 | 代码中创建 style，类似 CSS 状态样式 | 主题和资源体系更突出 |
| 应用组织 | 更偏 GUI 内核和控件库 | 更偏完整应用框架 |

### 4.3 移植差异

| 维度 | LVGL | AWTK |
| --- | --- | --- |
| 最小移植 | tick、flush、input、timer loop | 平台、lcd/canvas、input、main loop、资源 |
| MCU 小资源适配 | 非常常见，局部 buffer 模式成熟 | 也可适配，但资源和工程体系要规划 |
| 嵌入式 Linux | 支持 FBDEV、DRM、SDL 等方式 | 支持 Linux，并适合跨平台桌面调试 |
| 学习入口 | 最小 demo 很快跑起来 | 工程目录和资源工具需要一起理解 |

### 4.4 资源和工具链差异

| 维度 | LVGL | AWTK |
| --- | --- | --- |
| 图片字体 | 可转 C 数组，也可文件系统加载 | 更强调资源打包和统一管理 |
| UI 设计 | 代码方式常见，Pro Editor/XML 可选 | AWTK Designer 是重要配套 |
| 多语言/主题 | 支持，但项目需自己组织好 | 主题、多语言、资源体系更框架化 |
| 团队协作 | 程序员直接写 UI 很方便 | UI 设计、资源、业务代码分离更自然 |

### 4.5 选择建议

选型时不要只看“哪个框架更强”，而要看项目资源、页面规模、团队习惯和工具链要求。

优先考虑 LVGL 的情况：

- MCU RAM/Flash 紧张，需要轻量、可裁剪、移植成本低的 GUI 框架。
- 项目目标是快速点亮屏幕、跑通控件、验证交互，页面数量不多，资源管理不复杂。
- 团队主要是嵌入式 C 工程师，更习惯用 C API 直接组织界面、事件和业务逻辑。
- 希望社区资料、芯片厂 demo、RTOS/裸机/嵌入式 Linux 移植示例更多。
- 设备没有整屏 FrameBuffer，或者 RAM 不够大，需要成熟的局部 buffer 和脏区域刷新方案。

选择 LVGL 时要提前注意：

- 复杂应用里的页面跳转、资源目录、主题、多语言和业务架构需要团队自己规划。
- 如果大型项目完全靠 C 代码堆界面，后期维护成本可能上升。
- 中文字体、图片格式、颜色格式、`flush_cb`、线程安全和性能优化是常见风险点。
- 高分辨率、大量透明混合、复杂动画场景下，仍然要结合 DMA2D/GPU、缓存和刷新面积做优化。

优先考虑 AWTK 的情况：

- 项目页面较多、资源较多，主题、多语言、窗口生命周期和资源打包需求明显。
- 希望使用 Designer / XML 这类工具链，让 UI 描述、资源和业务逻辑分离。
- 项目跨平台诉求强，需要 PC 模拟、嵌入式运行、多端复用，或者希望桌面端调试更方便。
- 团队愿意接受 AWTK 的工程体系，把窗口、widget、资源、主题和事件绑定作为整体流程来管理。
- 项目更像一个完整 GUI 应用，而不是只需要几个简单控件的显示界面。

选择 AWTK 时要提前注意：

- 相比 LVGL，最小上手心智负担更重，需要同时理解 XML、资源包、控件命名、窗口生命周期和平台适配层。
- 在极小资源 MCU 上使用时，要认真评估裁剪、内存占用、资源打包和启动开销。
- 如果项目只是简单 UI，AWTK 的完整工程体系可能显得偏重。
- 社区规模和第三方资料相对 LVGL 少一些，遇到问题时更依赖官方文档、源码和工程经验。

一句话总结：

> 小资源、快移植、C 工程师主导、页面不复杂，优先看 LVGL；多页面、多资源、强工具链、跨平台和工程化诉求明显，优先看 AWTK。


## 5. 面试角度常见问题

### 5.1 LVGL 移植时最少要实现哪些东西？

至少需要：

- `lv_init()` 初始化。
- tick 时间基准。
- display 对象。
- draw buffer。
- flush 回调。
- input device 读取回调。
- 周期性调用 `lv_timer_handler()`。

回答时可以补一句：

> 如果屏幕不显示，先查 flush 是否被调用、area 是否正确、颜色格式是否正确、flush 完成后有没有调用 ready、LCD 驱动本身是否能单独画点。


### 5.2 LVGL 的 `flush_cb` 是干什么的？

`flush_cb` 是 LVGL 和底层显示驱动之间的桥。

LVGL 负责把某个区域渲染到缓冲区，`flush_cb` 负责把这块像素数据写到屏幕指定区域。

典型职责：

- 接收刷新区域 `area`。
- 接收像素缓冲 `px_map`。
- 调 LCD 驱动、DMA2D、SPI、FrameBuffer、DRM 等接口。
- 完成后通知 LVGL 本次 flush 完成。


### 5.3 LVGL 和 AWTK 你会怎么选型？

可以这样答：

> 如果项目资源紧张、UI 页面不算复杂、团队希望快速移植和开发，我更倾向 LVGL。它轻量、社区资料多，适合 MCU 和 RTOS 场景。如果项目页面多、资源多、需要可视化设计、主题、多语言、跨平台模拟和更完整的应用组织，我会考虑 AWTK。

再补充一句：

> 最终还要看团队经验、芯片资源、屏幕分辨率、动画复杂度、资源流程、维护周期和已有代码积累。


### 5.4 AWTK 的 Designer 和 XML 有什么价值？

价值主要是工程协作：

- UI 结构不完全写死在 C 代码里。
- 可以可视化设计和预览。
- 控件名称、资源、主题可以统一管理。
- 多页面项目更容易维护。
- UI 工程师和嵌入式工程师可以分工。

但也要说明代价：

- 要学习工具链。
- 要管理 XML、资源包和代码之间的关系。
- 调试时要确认运行时加载的是不是最新资源。


## 6. 项目经验回答模板

### 6.1 如果面试官问：你做过 LVGL/AWTK 吗？

可以按这个结构回答：

```text
我主要接触的是 xxx。
项目里它负责 xxx 屏幕的 UI 显示。
底层显示接口是 xxx，颜色格式是 xxx，分辨率是 xxx。
移植时主要实现了 tick、flush、输入读取和主循环。
页面上用了 button、label、image、list 等控件。
事件通过回调处理，后台任务通过消息队列通知 UI 线程刷新。
优化上主要做了局部刷新、图片预加载、字体裁剪、DMA 搬运和避免 UI 回调阻塞。
遇到的问题主要是花屏/触摸方向/中文字体/内存占用/动画卡顿，最后通过 xxx 解决。
```


## 7. 速记总结

### 7.1 LVGL 速记

- 关键词：轻量、C、对象树、控件、样式、事件、Flex/Grid、flush、局部 buffer。
- 最小移植：tick + display + buffer + flush + input + `lv_timer_handler()`。
- 适合：MCU、RTOS、裸机、嵌入式 Linux、快速移植。
- 风险点：线程安全、字体资源、颜色格式、flush、复杂页面工程组织。


### 7.2 AWTK 速记

- 关键词：跨平台、widget、window、XML、资源包、主题、Designer、main loop。
- 工程重点：UI 描述、资源管理、窗口生命周期、事件绑定。
- 适合：多页面、多资源、多语言、主题化、可视化设计、跨平台项目。
- 风险点：工具链学习、资源路径、控件查找、窗口生命周期、资源裁剪。


## 8. 参考资料

- LVGL 官方文档和仓库：LVGL 是开源 C 图形库，提供控件、样式、输入、显示、布局、渲染和移植接口。- https://lvgl.io/docs/open/introduction
- AWTK 官方仓库：AWTK 是 ZLG 开源跨平台嵌入式 GUI 引擎，提供 widget、资源、主题、Designer、跨平台适配等能力。- https://awtk.zlg.cn/docs/awtk_docs/AWTK_Guide/1.GettingStarted.html

