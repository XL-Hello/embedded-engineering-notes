# MIPI DSI 进阶：链路预算、传输语法与 Bring-up 调试

> **定位**：本文面向已经知道 MIPI DSI “是什么、有哪些模式”的读者，解决更靠后的一批问题：参数怎么算、链路上到底传了什么、面板如何初始化、怎样把一块新屏稳定点亮、异常时如何闭环定位。
>
> **主线**：全文不是按协议条款顺序罗列知识，而是围绕一次真实的显示屏 Bring-up，按照工程决策发生的顺序组织：
>
> **传输模型 → 链路预算 → 协议包 → 面板控制 → 最小点亮路径 → 调试闭环**
>
> **适用范围**：本文主要讨论经典 MIPI DSI + D-PHY 显示链路，重点覆盖嵌入式 SoC/MCU 上常见的 Video Mode、Command Mode、DCS、D-PHY、Linux/RTOS 驱动 Bring-up。DSI-2 的 VRR、VDC-M、DSE、A-PHY 等新特性不作为主线展开。
>
> **重要原则**：MIPI 规范定义“协议允许什么”，SoC DSI Host 手册定义“控制器怎么配”，Panel Datasheet 定义“这块屏接受什么”。三者发生冲突时，不能拿通用经验压过器件规格书。

---

## 第一章、先看全局：这篇文档到底解决什么问题

> 本章不讲寄存器和公式，只建立一张工程地图：各章分别解决什么问题、为什么按这个顺序排。

### 1.1、一句话理解本文

MIPI DSI Bring-up 的核心不是“把几个寄存器抄进去”，而是建立这条因果链：每一步的输出都是下一步的输入。

```text
面板规格        分辨率 / 刷新率 / porch / 像素格式
   ▼
显示传输模型    Video / Command、Sync Pulse / Sync Event / Burst、时钟策略
   ▼
链路预算        Pixel Clock → Aggregate Bitrate → Lane Rate → PLL/PHY 可配置值
   ▼
协议传输        Short / Long Packet、DT / VC、ECC / CRC、HS / LP / BTA
   ▼
面板初始化      Power / RESET → DCS / Generic → Sleep Out / Display On → Pixel Format / TE
   ▼
首帧            纯色 → 测试图 → 动态画面
   ▼
稳定性与调试    读回、错误寄存器、降速 / 改模式、示波器与 D-PHY 分析仪
```

所以“包格式”“DCS 命令”“链路速率”不是三个互不相关的百科词条，它们服务于同一个目标：

> **从一份 Panel Datasheet 出发，得到一套可解释、可验证、可稳定运行的 DSI 配置。**

---

### 1.2、六个工程问题与章节地图

第二～七章可以压缩成六个问题：

| 问题 | 章节 | 需要得到的答案 |
| --- | --- | --- |
| 这块屏应该怎样传一帧？ | 第二章 | Video/Command、Video 子模式、时钟策略 |
| 需要多大的链路带宽？ | 第三章 | Pixel Clock、Lane 数、Lane Rate、PLL/PHY 工作点 |
| 这些数据在线上长什么样？ | 第四章 | Packet、DT、VC、ECC、CRC、Video 包序列 |
| 面板为什么能被这些命令控制？ | 第五章 | DCS/Generic、上电时序、读回、TE、ULPS |
| 新屏应该按什么顺序点？ | 第六章 | 一条逐步收敛变量的 Bring-up 路径 |
| 画面异常以后怎么查？ | 第七章 | 从症状到层级、从免费信息到仪器的调试闭环 |

这个顺序不能随便换，因为后一个问题依赖前一个问题的结论：

- 不理解 Video Mode 的传输模型，就无法解释为什么要配 HSA/HBP/HFP；
- 不清楚 Pixel Clock 与 Lane Rate 的关系，就只能照抄厂商 PLL 参数；
- 不了解 Word Count、ECC、CRC，就很难解释“有图但随机雪花”；
- 分不清 DCS 的 Sleep Out 与 D-PHY 的 ULPS，就会把“面板睡眠”和“链路低功耗”混为一谈。

**读法**：第一次学习建议顺读；项目 Bring-up 时从第六章清单反查（不会算带宽→第三章，看不懂初始化表→第五章，CRC/ECC 错→第四章＋第七章）；已经出现异常则直接从第七章按症状进入。

全文使用同一块教学用虚拟面板（800×1280 @ 60 Hz、RGB888、4 Lane）贯穿计算、拆包、初始化与故障演示，参数表见 2.11。

---

### 1.3、三个层级必须始终分清

```text
应用/显示控制层    DCS、Generic Command、Panel 初始化、TE
        ▼
DSI 协议层         Packet、DT、VC、ECC、CRC、Video Packet Sequence
        ▼
D-PHY 物理层       HS/LP、Clock Lane、Data Lane、SoT/EoT、BTA、ULPS
```

几个典型混淆：

- `0x11 Sleep Out` 是 DCS 命令，不是 D-PHY 状态；
- `ULPS` 是 PHY 低功耗状态，不等于面板进入 Sleep；
- `CRC Error` 说明 Payload 校验失败，不等于 Framebuffer 内容本身错误；
- `HS/LP` 描述物理传输状态，`Short/Long Packet` 描述协议包结构，不是同一维度。

把层级混在一起，是很多 MIPI 文档“每句话都认识、合起来不知道在说什么”的根源。

---

## 第二章、显示传输模型：一帧画面到底怎样经过 DSI

> **本章解决的工程决策**：这块屏该使用 Video Mode 还是 Command Mode；使用 Video Mode 时选择哪一种子模式；Clock Lane 是否允许 Non-continuous。
>
> **为什么先讲模型再讲公式**：带宽计算不是孤立数学题。Video/Command、Burst/Non-Burst 会直接影响“什么时候必须发送数据、什么时候可以空闲、链路速率为什么需要高于平均像素率”。

### 2.1、先把“显示扫描”和“DSI 传输”分开

传统 RGB/DPI 显示接口非常直观：

```text
Pixel Clock 连续走
HSYNC 定义行
VSYNC 定义帧
DE 表示有效像素
RGB 数据跟着像素时钟输出
```

DSI 做的事情，本质上是把这套并行显示数据和控制事件**串行封装**。

因此要区分两个时间域：

```text
显示时间轴
┌────────────────────────────────────┐
│ VSYNC / VBP / Active / VFP         │
│ HSA / HBP / HACT / HFP             │
└────────────────────────────────────┘
                 │ 映射
                 ▼
DSI 链路时间轴
┌────────────────────────────────────┐
│ Sync Packet / Pixel Long Packet    │
│ Blanking / LP / BLLP / Command     │
└────────────────────────────────────┘
```

Video Mode 的目标是让 Panel 能够持续恢复或接受显示时序。

Command Mode 则更多依赖 Panel 内部 GRAM，Host 以“写内存”的方式更新图像。

---

### 2.2、Video Mode 的时序骨架

水平一行：

```text
|<--- HSA --->|<--- HBP --->|<------ HACT ------>|<--- HFP --->|
```

垂直一帧：

```text
| VSA | VBP |             VACT             | VFP |
```

对应定义：

| 参数 | 含义 | 是否显示像素 |
| --- | --- | --- |
| HSA | Horizontal Sync Active | 否 |
| HBP | Horizontal Back Porch | 否 |
| HACT | Horizontal Active | 是 |
| HFP | Horizontal Front Porch | 否 |
| VSA | Vertical Sync Active | 否 |
| VBP | Vertical Back Porch | 否 |
| VACT | Vertical Active | 是 |
| VFP | Vertical Front Porch | 否 |

总长度：

```text
HTOTAL = HSA + HBP + HACT + HFP
VTOTAL = VSA + VBP + VACT + VFP
```

这些“空白区”不是因为工程师喜欢浪费带宽。

它们来自显示扫描系统对：

- 行/场同步；
- TCON 内部准备时间；
- Source/Gate Driver 切换；
- 面板历史兼容；

等时序约束。

**不能因为这些区域“不显示图像”就随便改成 0。**

---

### 2.3、porch 参数从哪里来

优先级：

```text
Panel Datasheet 推荐值
    >
Panel Vendor Reference Driver
    >
已量产 BSP
    >
基于范围自行尝试
```

Datasheet 常见写法：

```text
HFP: min / typ / max
HBP: min / typ / max
HSYNC: min / typ / max
Pixel Clock: min / typ / max
```

如果给的是范围，通常优先从 `typ` 开始。

如果只给 Pixel Clock 和总时序，可以反推刷新率：

```text
FPS = PCLK / (HTOTAL × VTOTAL)
```

如果只知道分辨率，**不能唯一推出 porch**。

800×1280 并不意味着世界上所有 800×1280 面板都能共用同一组 timing。遗憾的是，分辨率并不是身份证号。

---

### 2.4、Video Mode 的三种子模式

经典 DSI Video Mode 有三种常见形式：

1. Non-Burst Mode with Sync Pulses
2. Non-Burst Mode with Sync Events
3. Burst Mode

#### 2.4.1、Non-Burst with Sync Pulses

目标：

> 尽量准确传达传统 DPI 时序，包括同步脉冲宽度。

典型概念序列：

```text
HSS → HSA interval → HSE → HBP → RGB → HFP
```

垂直方向也可使用 VSS/VSE 表示 VSYNC 的开始/结束。

特点：

- Panel 可较完整地恢复原始 sync pulse；
- 链路传输节奏与显示像素节奏关系紧；
- 常见于明确要求 Sync Pulse 的 Panel。

---

#### 2.4.2、Non-Burst with Sync Events

它不要求把完整同步脉冲宽度作为 start/end 两个事件都明确传递。

典型思路：

```text
HSS → HBP/Blanking → RGB → HFP/Blanking
```

Panel 根据 Sync Event 与已知 timing 重建需要的时序。

特点：

- 比 Sync Pulse 省掉部分同步结束事件；
- RGB 像素仍按与显示扫描相匹配的节奏传输；
- 具体 HSE/VSE 是否使用由模式与 Host 配置决定。

---

#### 2.4.3、Burst Mode

Burst Mode 的核心不是“不要 porch”，而是：

> **把有效像素数据用高于平均像素流所需的瞬时速率压缩在更短时间内发完。**

于是：

```text
一行总时间固定
┌──────────────────────────────────┐
│      快速发送 RGB      │  空闲区  │
└──────────────────────────────────┘
```

空出来的时间可以用于：

- 进入 LP；
- 执行其它允许的链路事务；
- 降低整体 PHY 活跃时间。

所以 Burst Mode 常有功耗优势。

但前提是：

```text
瞬时 DSI 带宽 > 平均视频数据需求
```

否则没有“burst”空间。

---

### 2.5、一个必须修正的常见误解：Non-Burst 不等于永远保持 HS

过度简化的说法常写成：

```text
Non-Burst：消隐期一直 HS + 填包
Burst：消隐期回 LP
```

这不够准确。

在 Non-Burst 模式中，HSA/HBP/HFP 等时间可以用 Blanking Packet 保持精确时长；**如果控制器、Panel 和时间预算允许完成 HS→LP→HS 的状态切换，也可以用 LP 时间替代部分 Blanking 区间。**

所以更准确地说：

| 模式 | 有效像素 | 消隐/空闲时间 |
| --- | --- | --- |
| Non-Burst | 按显示节奏发送 | 可用 Blanking/Null；部分实现允许合适时机进入 LP |
| Burst | 时间压缩发送 | 更容易形成较长 BLLP/LP 空闲窗口 |

这里的关键不是“能不能 LP”，而是：

> **Burst 更主动地制造可利用的空闲时间。**

---

### 2.6、Blanking Packet、Null Packet 和 BLLP

#### Blanking Packet

Data Type：

```text
0x19
```

它是 Long Packet，用来占据本来属于显示 blanking 的链路时间。

它的作用不是“显示黑色像素”。

Panel 在 blanking 区间不会把这些 payload 当作有效图像显示。

#### Null Packet

Data Type：

```text
0x09
```

用于填充链路时间，但语义上不是显示 blanking 本身。

具体 Host IP 在某些区域发送 Blanking 还是 Null，通常有配置选项。

#### BLLP

常见缩写：

```text
BLLP = Blanking or Low-Power Interval
```

指 Video Mode 中没有正在传输像素/同步视频包的可利用区间。

可能被：

- Blanking Packet；
- Null Packet；
- LP 状态；
- 某些允许插入的命令；

占用。

---

### 2.7、Command Mode：它不是“没有时序”，而是时序约束换了形式

Command Mode 常被粗暴总结成：

> “Command Mode 没有 porch。”

从 DSI **链路传输模型**看，它确实不像 Video Mode 那样必须持续把完整 DPI raster timing 串行化。

但这不代表系统没有显示扫描时序。

典型 Command Mode Panel 内部有 GRAM：

```text
Host
  │  DCS 0x2A / 0x2B 设置窗口
  │  DCS 0x2C 写像素
  ▼
Panel GRAM
  │
  ▼
Panel 内部 TCON 按自己的扫描节奏刷新屏幕
```

Host 不需要每一帧都持续发送完整 porch。

但需要考虑：

- Panel 内部刷新频率；
- GRAM 写入速度；
- TE 同步；
- 一次更新的数据量；
- 是否允许局部刷新；
- 写入过程是否会与扫描冲突。

---

### 2.8、TE 的正确理解

TE：

```text
Tearing Effect
```

Panel 可以通过 TE 信号告诉 Host 一个适合开始更新的同步点。

常见实现：

- 独立 TE GPIO；
- 某些 DSI 系统中的 TE Trigger Message；
- Host 控制器硬件 TE 输入。

错误说法：

> “一帧必须严格在两个 TE 之间传完，否则一定撕裂。”

更准确的说法：

> Host 应根据 Panel 对 TE 的定义和 GRAM/扫描机制，把更新放在不会与显示扫描发生可见冲突的窗口内。对于整帧高速写入，常见设计目标是一次更新在可用帧周期内完成；但实际允许的开始时刻、窗口长度和是否支持跨周期写入必须看 Panel 手册。

局部刷新时：

```text
传输数据量 = 更新区域宽 × 更新区域高 × bpp
```

因此比整帧更容易满足时间预算。

---

### 2.9、Continuous Clock 与 Non-Continuous Clock

D-PHY Clock Lane 在 HS 传输期间给 Data Lane 提供 HS 时钟。

两种常见策略：

#### Continuous Clock

即使当前没有有效 HS payload，Clock Lane 也尽量保持 HS clock。

优点：

- 状态简单；
- 避免频繁 Clock Lane LP↔HS；
- Bring-up 阶段变量少；
- 某些 Panel 明确要求。

代价：

- 功耗更高；
- EMI 活跃时间更长。

#### Non-Continuous Clock

在允许的空闲区间，Clock Lane 可以返回 Stop State，典型为 LP-11。

优点：

- 降低 PHY 活跃时间；
- 有利于低功耗。

代价：

- 增加状态切换；
- 对 D-PHY timing 配置与 Panel 兼容性要求更高。

Linux DRM 中常见：

```c
MIPI_DSI_CLOCK_NON_CONTINUOUS
```

它表示设备支持/使用 non-continuous clock 行为。

**Bring-up 初期如果 Panel 支持 continuous clock，通常先用 continuous，稳定以后再打开低功耗优化。**

这是调试策略，不是 MIPI 规范硬性要求。

---

### 2.10、模式选择决策表

| 条件 | 更倾向的方案 | 原因 |
| --- | --- | --- |
| Panel Datasheet 明确指定模式 | 按 Datasheet | 最高优先级 |
| 无 GRAM、持续视频流 | Video Mode | 必须持续输送像素 |
| 有 GRAM、静态 GUI、多局部更新 | Command Mode | 可按需更新 |
| 要完整恢复 HSYNC pulse | Non-Burst Sync Pulse | 同步信息最完整 |
| Panel 支持 event timing | Non-Burst Sync Event | 减少同步事件 |
| 追求降低 PHY 活跃时间 | Burst | 通过时间压缩形成空闲 |
| Bring-up 初期 | Panel 支持的最简单模式 | 减少变量 |
| 低功耗优化 | Burst + 合适的 Non-continuous Clock | 需 Panel/Host 均支持 |

不能只根据“哪个更先进”选。

真正的决策树：

```text
Panel 支持什么？
      │
      ▼
SoC Host 支持什么？
      │
      ▼
带宽够不够？
      │
      ▼
功耗/EMI/刷新策略有什么要求？
      │
      ▼
选择模式
```

---

### 2.11、贯穿案例的模式选择

全文使用同一块**教学用虚拟面板**贯穿计算、拆包、初始化与故障演示。

> 下面参数只用于演示方法，不对应任何真实 Panel。实际项目必须替换为真实 Datasheet 参数。

| 参数 | 教学值 | 参数 | 教学值 |
| --- | ---: | --- | ---: |
| HACT | 800 pixel | VACT | 1280 line |
| HSA / HBP / HFP | 10 / 20 / 20 | VSA / VBP / VFP | 2 / 8 / 8 |
| Refresh Rate | 60 Hz | Pixel Format | RGB888，24 bpp |
| Data Lane | 4 | DSI Mode | Video Mode |

因此 `HTOTAL = 800 + 10 + 20 + 20 = 850`，`VTOTAL = 1280 + 2 + 8 + 8 = 1298`，第三章起直接引用这两个值。

为了先得到稳定可解释的链路，本篇选择：

```text
Non-Burst with Sync Events
Continuous Clock
```

原因：

- 不是为了宣称它“最好”；
- 而是避免在主算例一开始就同时引入 Burst 与 Non-continuous Clock 两个变量；
- 后续再说明如果改成 Burst，带宽与 LP 空间如何变化。

---

## 第三章、链路预算：从分辨率算到 Lane Rate 与 PHY 工作点

> **本章解决的工程决策**：这块屏在当前 Lane 数和像素格式下是否跑得动；需要多大的 DSI 数据率；Host 和 Panel 的速率范围是否有交集。
>
> 本章最重要的原则：
>
> **公式先给“理论需求”，真正可用的配置还必须落回 SoC 与 Panel 的离散约束。**

### 3.1、先建立输入参数表

不要上来就算。

先把参数分成三类。

#### A. Panel 显示输入

```text
HACT
HSA
HBP
HFP
VACT
VSA
VBP
VFP
FPS
Pixel Format
```

#### B. DSI 约束

```text
Video / Command
Video 子模式
Lane 数
Panel min/max Lane Rate
Continuous / Non-continuous Clock
```

#### C. SoC 约束

```text
Host 支持的 Lane 数
每 Lane min/max Rate
PLL / Divider 可配置范围
D-PHY timing 参数
Host FIFO / packetization 约束
```

把“规格书参数”和“自己算出来的参数”混在一张表里而不标来源，后面几乎必然会出现单位灾难。

---

### 3.2、Video Mode 第一步：Pixel Clock

Video Mode 常用一阶计算：

```text
PCLK = HTOTAL × VTOTAL × FPS
```

其中：

```text
HTOTAL = HACT + HSA + HBP + HFP
VTOTAL = VACT + VSA + VBP + VFP
```

贯穿案例：

```text
HTOTAL = 850
VTOTAL = 1298
FPS    = 60
```

所以：

```text
PCLK
= 850 × 1298 × 60
= 66,198,000 pixel/s
≈ 66.198 MHz
```

注意：

> 这里的 MHz 表示每秒约 66.198M 个 pixel clock 周期，不是 D-PHY Clock Lane 的频率。

---

### 3.3、为什么不能只用 HACT × VACT × FPS

有效像素率：

```text
800 × 1280 × 60
= 61.44 Mpixel/s
```

小于完整 Pixel Clock：

```text
66.198 Mpixel/s
```

差值来自：

```text
H/V blanking
```

在 Video Mode 下，Host 仍必须满足完整的行/帧时间。

因此做基础带宽预算时常以：

```text
HTOTAL × VTOTAL × FPS
```

为基准。

这也是很多 SoC 厂商 DSI bandwidth 估算公式的基础。

---

### 3.4、第二步：确定链路上的有效 bpp

常见 RGB Pixel Stream：

| Pixel Format | DSI 传输特性 | 基础带宽估算 |
| --- | --- | ---: |
| RGB565 | 16-bit packed | 16 bpp |
| RGB666 packed | 18-bit packed | 18 bpp |
| RGB666 loosely packed / 3-byte | 每像素占 3 byte | 24 bit/pixel 的链路占用 |
| RGB888 | 每像素 3 byte | 24 bpp |

最容易错的是 RGB666。

#### RGB666 Packed

4 个像素：

```text
4 × 18 bit = 72 bit = 9 byte
```

是真正 18 bpp 的紧凑传输。

#### RGB666 Loosely Packed

每个像素占：

```text
3 byte = 24 bit
```

虽然只有 18 bit 有效颜色数据，但链路上仍按 3 byte/pixel 占用。

因此：

> “面板是 18-bit 色深”不一定意味着链路预算直接乘 18。

必须看 DSI Pixel Stream Data Type。

---

### 3.5、第三步：最小 aggregate bandwidth

Video Mode 的一阶最小链路带宽：

```text
AggregateBW_min = PCLK × bpp
```

贯穿案例：

```text
PCLK = 66.198 MHz
bpp  = 24
```

得到：

```text
AggregateBW_min
= 66.198M × 24
= 1,588.752 Mbit/s
≈ 1.589 Gbit/s
```

4 条 Data Lane 平均分担：

```text
LaneRate_min
= AggregateBW_min / Nlane
= 1,588.752 / 4
= 397.188 Mbit/s
```

所以理论最低约：

```text
397.2 Mbps/lane
```

---

### 3.6、这是不是最终 Lane Rate？不是

`PCLK × bpp / Lane` 是非常重要的**基线**，但还不是可以盲目写进寄存器的最终数字。

实际传输还涉及：

- Packet Header；
- Long Packet CRC；
- Sync Event；
- EoTp；
- Blanking / Null Packet；
- HS↔LP 状态切换开销；
- Host 内部 packetizer/FIFO 约束；
- Burst/Non-Burst 模式行为；
- PLL 离散档位。

所以正确流程是：

```text
理论最低需求
    ↓
Host 对该模式的 timing/bandwidth 公式
    ↓
选择一个 SoC 实际可配置的 Lane Rate
    ↓
确认不超过 Panel 最大值，也不低于 Panel/PHY 最小值
    ↓
验证行时间与 packetization 能否成立
```

---

### 3.7、不要把“固定留 10%/20%”当成协议规则

工程文章很喜欢写：

```text
LaneRate = 理论值 × 1.2
```

然后仿佛 20% 是 MIPI 联盟刻在石碑上的数字。

不是。

Margin 应该来自：

- Host IP 的计算要求；
- PLL 可选档位；
- Panel min/max；
- D-PHY timing；
- Burst 所需的时间压缩比例；
- 实测 SI 余量。

可以在没有厂商推荐值时把“向上选择一个合理档位”作为初始工作点，但必须明确：

> **这是工程起点，不是规范公式。**

---

### 3.8、Non-Burst 与 Burst 的速率关系

#### Non-Burst

目标是维持显示 timing。

很多 Host 中：

```text
视频输入数据率 ≈ PHY 可承载视频数据率
```

更高的 PHY rate 会由：

- Blanking；
- Null；
- LP interval；

等机制吸收时间差，但能否这样配置取决于 Host packetizer。

#### Burst

必须有：

```text
PHY 实际发送像素的瞬时速率
>
平均视频像素数据需求
```

否则像素无法在更短时间内发完，也就没有可释放的 BLLP。

因此 Burst 的 Lane Rate 通常不能简单设成“刚好等于平均最低值”。

---

### 3.9、第四步：D-PHY Clock Lane 与 Byte Clock

经典 D-PHY HS Data Lane 是 DDR。

因此：

```text
LaneRate = 2 × Fclk_hs
```

若：

```text
LaneRate = 500 Mbps
```

则 Clock Lane HS 频率约为：

```text
Fclk_hs = 250 MHz
```

Lane Byte Clock：

```text
ByteClk = LaneRate / 8
        = 62.5 MHz
```

三个量不要混：

```text
500 Mbps     ← bit rate
250 MHz      ← HS clock frequency
62.5 MHz     ← byte clock
```

这是 MIPI 配置里最常见的“三胞胎冒名顶替案”。

---

### 3.10、PLL 配置为什么不能给一套通用公式

不同 DSI Host 的内部时钟树完全可能不同：

```text
XTAL
  ↓
PLL
  ↓
VCO
  ├─ divider → PHY bit clock
  ├─ divider → byte clock
  └─ divider → escape clock
```

另一个 SoC 可能是：

```text
PLL output
   ↓ /2
HS clock
   ↓ /4
byte clock
```

因此通用文档最多只能给出：

```text
目标 LaneRate
→ 查 Host PLL 公式
→ 枚举合法 M/N/P
→ 得到最接近且不低于需求的实际值
→ 再反算实际 LaneRate
```

不能把某颗 STM32、Rockchip、NXP 的 PLL 公式复制出来冒充 MIPI 公式。

---

### 3.11、Panel 与 SoC 的速率窗口必须有交集

假设：

```text
计算需要：≥ 397 Mbps/lane
Panel 支持：80 ~ 1000 Mbps/lane
SoC 支持：160 ~ 1500 Mbps/lane
```

交集：

```text
397 ~ 1000 Mbps/lane
```

如果 SoC PLL 可选：

```text
400 / 450 / 500 / 600 Mbps
```

那么：

- 400 Mbps 理论上太贴边；
- 450/500 Mbps 更适合作为初始工作点；
- 是否能用 500 仍需确认 Host 在当前 Video Mode 下的 line timing 配置。

如果：

```text
Panel max = 450 Mbps
SoC 最低可稳定档 = 500 Mbps
```

即使总带宽“数学上够”，系统仍然不可行。

---

### 3.12、贯穿案例的建议工作点

理论：

```text
LaneRate_min ≈ 397.188 Mbps
```

假设教学 SoC 和 Panel 都支持 500 Mbps/lane，则先选：

```text
LaneRate = 500 Mbps/lane
```

对应：

```text
AggregateBW = 2.0 Gbit/s
Fclk_hs     = 250 MHz
ByteClk     = 62.5 MHz
```

相对理论基线：

```text
2.0 / 1.588752 ≈ 1.259
```

也就是约 25.9% 的带宽空间。

再次强调：

> 这个 500 Mbps 是教学选点，不是对所有 800×1280 面板的推荐值。

---

### 3.13、Command Mode 的预算方法

Command Mode 更适合从“必须在多长时间内写完多少数据”出发。

整帧数据量：

```text
FrameBits = Width × Height × bpp
```

假设：

```text
454 × 454
RGB888
```

则：

```text
FrameBits
= 454 × 454 × 24
= 4,946,784 bit
```

如果希望在：

```text
14 ms
```

内完成整帧写入：

```text
AggregateBW_payload
= 4,946,784 / 0.014
≈ 353.34 Mbps
```

两 Lane：

```text
≈ 176.67 Mbps/lane
```

这仍只是 payload 基线。

还需要考虑：

- DCS/Long Packet 开销；
- BTA/TE 等控制事务；
- Host FIFO；
- LP/HS 切换；
- 实际允许写 GRAM 的窗口。

最终选择的 Lane Rate 应高于这个 payload rate，并符合 Panel/Host 限制。

---

### 3.14、Command Mode 的局部刷新为什么很省带宽

如果只更新：

```text
100 × 100
RGB888
```

数据量：

```text
100 × 100 × 24
= 240,000 bit
= 30,000 byte
```

相比 454×454 全帧：

```text
30 KB
vs
约 618 KB
```

这也是 Command Mode 在：

- 手表；
- 小屏 GUI；
- 静态界面；

中很有价值的原因之一。

但前提是 Panel 的 GRAM、地址窗口和刷新机制支持。

---

### 3.15、Packet 开销应该怎样估

以一条 RGB Long Packet 为例：

```text
Header  = 4 byte
Payload = W × bytes_per_pixel
CRC     = 2 byte
```

如果 800 pixel、RGB888：

```text
Payload = 800 × 3 = 2400 byte
Packet  = 2406 byte
```

单纯 Long Packet 协议开销：

```text
6 / 2400 ≈ 0.25%
```

看起来很小。

但整条 Video line 还可能有：

- HSS/HSE；
- Blanking；
- EoTp；
- 状态切换；

所以不要把 `0.25%` 当成整条链路的总开销。

分辨率越小、每行 payload 越短，固定 packet 开销占比越明显。

---

### 3.16、算不通时有哪些旋钮

| 手段 | 带宽影响 | 代价 |
| --- | --- | --- |
| 降刷新率 | 近似线性下降 | 动态流畅度降低 |
| 降色深 | 近似线性下降 | 色彩精度下降 |
| 增加 Lane | 单 Lane Rate 降低 | SoC/Panel/PCB 必须支持 |
| 缩短 blanking | PCLK 下降 | 受 Panel timing min 限制 |
| 使用 DSC | 显著降低传输带宽 | Host/Panel 都需支持，系统复杂 |
| 改 Command/局刷 | 视内容显著降低平均流量 | Panel 必须有 GRAM/相应模式 |

绝对不能做的事：

```text
为了让公式好看，把 HBP/HFP 随便减到 0
```

除非 Panel 明确允许。

---

### 3.17、如何反向校验一份现有驱动

拿到：

```text
lane_rate = 700 Mbps
lanes = 4
RGB888
800×1280@60
```

先反推最大理论 Pixel Clock：

```text
PCLK_equiv
= LaneRate × Nlane / bpp
= 700M × 4 / 24
≈ 116.67 MHz
```

而 Panel timing 需要：

```text
66.198 MHz
```

说明纯带宽角度充足。

接下来不能停止。

继续看：

- Host line timer 是否按 700 Mbps 正确换算；
- Panel 是否允许 700 Mbps；
- D-PHY timing 是否按 700 Mbps 重新计算；
- Burst/Non-Burst 配置是否与 Panel 一致；
- Byte Clock/escape clock 是否满足 Host 约束。

“总带宽够”只证明没有在第一关就死掉。

---

### 3.18、链路预算最终表模板

```text
[Panel]
Resolution        : ____ × ____
FPS               : ____
HSA/HBP/HFP       : ____ / ____ / ____
VSA/VBP/VFP       : ____ / ____ / ____
Pixel Format      : ____
Panel Lane Range  : ____ ~ ____ Mbps

[Calculation]
HTOTAL            : ____
VTOTAL            : ____
PCLK              : ____ MHz
bpp on DSI        : ____ bit
AggregateBW_min   : ____ Gbps
LaneRate_min      : ____ Mbps/lane

[Selected]
Lane Count        : ____
Actual Lane Rate  : ____ Mbps/lane
HS Clock          : ____ MHz
Byte Clock        : ____ MHz

[Check]
SoC Range         : PASS / FAIL
Panel Range       : PASS / FAIL
Video timing      : PASS / FAIL
PLL realizable    : PASS / FAIL
```

---

## 第四章、传输语法：DSI 在线上到底发了什么

> **本章解决的工程决策**：看到一段抓包、Host 日志或错误寄存器时，能判断问题发生在 Header、Payload、Data Type、Virtual Channel，还是物理传输阶段。
>
> 第二章讲“什么时候传”，本章讲“那段时间里究竟传了什么”。

### 4.1、先分清两个维度：HS/LP 与 Short/Long Packet

这两个概念经常被写在一起，于是读者很自然地以为：

```text
HS = Long Packet
LP = Short Packet
```

这是错的。

它们分别属于两个维度：

| 维度 | 描述什么 |
| --- | --- |
| HS / LP | D-PHY 用什么电气状态传输 |
| Short / Long Packet | DSI 协议层的包结构 |

在具体实现允许的情况下：

- Short Packet 可以通过 HS 发送；
- Long Packet 也可以作为 LPDT 发送；
- Video Pixel Stream 通常走 HS；
- 反向读回必须使用 Lane 0 的 LP 反向链路。

所以调试时不要看到“DCS Short Write”就自动理解成“LP”。

---

### 4.2、Data Identifier：一个字节里同时装 DT 和 VC

经典 DSI Packet 的第一个字节叫：

```text
Data Identifier, DI
```

经典格式：

```text
bit7 bit6 | bit5 ........ bit0
   VC     |      DT
```

即：

```text
DI[7:6] = Virtual Channel
DI[5:0] = Data Type
```

经典 2-bit VC 可表达：

```text
VC0 ~ VC3
```

Data Type 决定：

- 这是同步事件；
- Pixel Stream；
- Generic Write；
- DCS Write；
- Read Request；
- Blanking/Null；
- EoTp；

等哪一种事务。

---

### 4.3、Short Packet：固定 4 Byte

结构：

```text
Byte0       Byte1        Byte2       Byte3
+-----------+------------+-----------+------+
| Data ID   | Data0      | Data1     | ECC  |
+-----------+------------+-----------+------+
```

总长度固定：

```text
4 byte
```

其中 Byte1/Byte2 的含义由 Data Type 决定。

例如：

#### DCS Short Write，无参数

```text
DT = 0x05
Data0 = DCS Command
Data1 = 0x00
```

例如发送：

```text
Sleep Out = 0x11
```

协议语义上可表示为：

```text
DI = DCS Short Write
Data0 = 0x11
Data1 = 0x00
ECC
```

#### DCS Short Write，一个参数

```text
DT = 0x15
Data0 = DCS Command
Data1 = Parameter
```

例如：

```text
0x3A, 0x77
```

含义：

```text
Set Pixel Format → 24-bit
```

如果 Panel 与 DCS 版本支持该格式配置。

---

### 4.4、Long Packet：Header + Payload + CRC

结构：

```text
              4-byte Header
+---------+---------+---------+------+
| Data ID | WC LSB  | WC MSB  | ECC  |
+---------+---------+---------+------+
|                                    |
|             Payload                |
|          0 ~ 65535 byte            |
|                                    |
+-------------------+----------------+
| CRC LSB           | CRC MSB        |
+-------------------+----------------+
```

所以总长度：

```text
4 + WC + 2
```

即：

```text
6 ~ 65541 byte
```

`Word Count` 表示：

> Payload 的**字节数**，不是像素数，也不是 bit 数。

---

### 4.5、Word Count 怎么算

#### RGB888，一行 800 pixel

```text
WC = 800 × 3
   = 2400 byte
```

#### RGB565，一行 800 pixel

```text
WC = 800 × 2
   = 1600 byte
```

#### RGB666 Loosely Packed

每 pixel 3 byte：

```text
WC = Width × 3
```

#### RGB666 Packed

4 pixel = 9 byte。

因此 Width 最好满足相应 pixel-group 打包要求，Host 也可能对 packet chunk 有额外限制。

这里必须区分：

- **协议数据类型自身的打包规则**；
- **Host FIFO/DMA 要求的 4-byte/8-byte alignment**。

后者是控制器实现要求，不应写成 DSI Long Packet 的通用“Payload 必须 4 字节对齐”。

---

### 4.6、ECC 到底保护什么

Packet Header 的前三个字节：

```text
Data ID
Word Count/Data0
Word Count/Data1
```

由 Header ECC 保护。

也就是说，Long Packet 中：

```text
[ Data ID | WC LSB | WC MSB ] → ECC
```

Short Packet 中：

```text
[ Data ID | Data0 | Data1 ] → ECC
```

经典 DSI Header ECC 能够：

- 对单 bit header error 进行纠正；
- 检测双 bit error；
- 多 bit 情况下不保证可纠正。

工程含义：

如果 Host/Panel 报：

```text
Single-bit ECC
```

说明至少 Header 传输已经出现 bit error，但可能被纠正。

如果持续出现：

```text
Multi-bit ECC
```

说明 Header 已经不可靠。

重点检查：

- D-PHY timing；
- Lane signal integrity；
- Lane mapping/polarity；
- 速率余量；
- 时钟与数据稳定性。

---

### 4.7、CRC 到底保护什么

Long Packet Payload 后带：

```text
16-bit CRC
```

常见 DSI checksum 使用生成多项式：

```text
x^16 + x^12 + x^5 + 1
```

它用于检测 Payload 传输错误。

最重要的区别：

```text
ECC → Header
CRC → Long Packet Payload
```

CRC 不是纠错码。

所以：

> **CRC Error 说明接收端认为 Payload 内容在传输过程中发生了错误；协议本身不会因为 CRC Error 自动把那几个错误 bit 恢复成正确值。**

如果 Pixel Long Packet 出现 CRC Error，画面上可能出现：

- 雪花；
- 彩点；
- 局部错误；
- 行内随机破坏；

具体表现取决于 Panel 对错误包的处理。

---

### 4.8、为什么 ECC Error 和 CRC Error 的排查价值不同

假设：

```text
Case A:
ECC Error 很多
CRC Error 很少
```

优先怀疑：

- Header 也在出错；
- 整体 PHY 可靠性已经比较差；
- Data Type/VC/WC 可能被误解析。

假设：

```text
Case B:
Header 正常
CRC Error 随温度/速率增加
```

更像：

- HS Payload bit error；
- SI/PHY timing margin 不足。

假设：

```text
Case C:
没有 ECC/CRC Error
但颜色完全错
```

优先看：

- RGB/BGR；
- Pixel Format；
- Data Type；
- Framebuffer format；
- MADCTL/address mode；
- byte ordering。

错误寄存器不是万能的，但它至少能阻止工程师把每个花屏都归罪给 porch。

---

### 4.9、主要 Processor-to-Peripheral Data Type 速查

下面列出经典 DSI 工程中最常见的 DT。

#### 同步/控制类

| DT | 含义 |
| ---: | --- |
| `0x01` | V Sync Start |
| `0x11` | V Sync End |
| `0x21` | H Sync Start |
| `0x31` | H Sync End |
| `0x08` | End of Transmission Packet |
| `0x09` | Null Packet，Long |
| `0x19` | Blanking Packet，Long |

#### Generic Command

| DT | 含义 |
| ---: | --- |
| `0x03` | Generic Short Write，0 参数 |
| `0x13` | Generic Short Write，1 参数 |
| `0x23` | Generic Short Write，2 参数 |
| `0x04` | Generic Read Request，0 参数 |
| `0x14` | Generic Read Request，1 参数 |
| `0x24` | Generic Read Request，2 参数 |
| `0x29` | Generic Long Write |

#### DCS Command

| DT | 含义 |
| ---: | --- |
| `0x05` | DCS Short Write，0 参数 |
| `0x15` | DCS Short Write，1 参数 |
| `0x06` | DCS Read |
| `0x39` | DCS Long Write |
| `0x37` | Set Maximum Return Packet Size |

#### RGB Pixel Stream

| DT | 含义 |
| ---: | --- |
| `0x0E` | Packed Pixel Stream, 16-bit RGB565 |
| `0x1E` | Packed Pixel Stream, 18-bit RGB666 |
| `0x2E` | 18-bit RGB666，3-byte/loosely packed 形式 |
| `0x3E` | Packed Pixel Stream, 24-bit RGB888 |

这些 DT 是第四章和第五章之间的桥。

例如：

```text
DCS 命令 0x11
```

和：

```text
DT = 0x05
```

不是同一个东西。

前者表示：

```text
“命令语义是 Sleep Out”
```

后者表示：

```text
“用 DCS Short Write 这种 DSI Packet 发送”
```

---

### 4.10、Peripheral-to-Processor 常见返回包

读操作后，Panel 返回的包也有 Data Type。

常见包括：

| DT | 含义 |
| ---: | --- |
| `0x02` | Acknowledge and Error Report |
| `0x11` | Generic Short Read Response, 1 byte |
| `0x12` | Generic Short Read Response, 2 byte |
| `0x1A` | Generic Long Read Response |
| `0x1C` | DCS Long Read Response |
| `0x21` | DCS Short Read Response, 1 byte |
| `0x22` | DCS Short Read Response, 2 byte |

因此读回失败时不能只问：

> “有没有数据？”

还应该问：

- 返回的 DT 是什么；
- 是 ACK/Error Report 还是 Read Response；
- 返回长度与预期是否一致；
- Host 是否正确配置 Maximum Return Packet Size；
- BTA 是否成功完成。

---

### 4.11、Virtual Channel：单屏常用 VC0，但不要写死成协议要求

很多单 Panel 项目：

```text
VC = 0
```

于是很容易总结：

> “单屏固定 VC0。”

更准确的说法：

> 单屏项目通常配置 VC0，但 VC 是链路配置的一部分，Host 与 Peripheral 必须一致；不能把 VC0 当成协议硬性规定。

如果 Host 发 VC1，而 Panel 只监听 VC0：

- D-PHY 可能完全正常；
- Packet ECC/CRC 也可能正常；
- 但 Panel 不一定接受这些包。

这类问题很适合制造一种令人愉快的黑屏：所有电气指标都很好，画面就是没有。

---

### 4.12、EoTp：不要和 D-PHY 的电气 EoT 混在一起

DSI 定义：

```text
End of Transmission Packet
DT = 0x08
```

常简称：

```text
EoTp
```

它是协议层 Packet。

同时 D-PHY 从 HS 返回 LP/Stop State 还有物理层的 End-of-Transmission sequence。

两者不要混为一谈。

Linux DRM 里可见：

```c
MIPI_DSI_MODE_NO_EOT_PACKET
```

说明实际系统中 EoTp 是否发送可能是可配置项。

处理原则：

```text
Panel 明确要求/禁止 → 按 Panel
Host 默认行为      → 查 Host
参考 BSP           → 用于佐证
```

不要因为“另一块屏关了 EoTp 能亮”就迁移到当前 Panel。

---

### 4.13、把一条 Video Active Line 拆开

教学面板：

```text
HACT = 800
RGB888
```

有效像素包：

```text
Data Type = 0x3E
WC        = 2400
```

抽象表示：

```text
[HSS]
   ↓
[HBP / LP / Blanking]
   ↓
[RGB888 Long Packet]
 Header:
   DI = VC + 0x3E
   WC = 2400
   ECC
 Payload:
   Pixel0 ... Pixel799
 CRC16
   ↓
[HFP / LP / Blanking]
```

如果是 Sync Pulse：

```text
HSS
→ HSA interval
→ HSE
→ HBP
→ RGB
→ HFP
```

如果是 Sync Event：

```text
HSS
→ blanking
→ RGB
→ blanking
```

如果是 Burst：

```text
HSS/event
→ 快速 RGB burst
→ 更长 BLLP/LP
```

这就是第二章的“时间轴”被第四章 Packet 填满后的样子。

---

### 4.14、一帧 Video Mode 可以怎样理解

简化为：

```text
VSS
│
├─ VSA lines
├─ VBP lines
│
├─ Active line 0
│    ├─ H sync event
│    ├─ H blanking
│    ├─ RGB Long Packet
│    └─ H blanking
│
├─ Active line 1
│    ...
│
├─ Active line 1279
│
└─ VFP lines
```

真实 Host 的 packet sequence 取决于：

- Video 子模式；
- 是否发 HSE；
- HSA/HBP/HFP 是否允许 LP；
- EoTp 设置；
- Null/Blanking 选择；
- Host 的 BLLP 策略。

所以抓包时不要要求所有厂商 Host 都生成完全相同的“艺术作品”。

---

### 4.15、Packet 层调试最值得记录什么

推荐日志：

```text
DSI TX:
VC
DT
payload length
LP/HS flag
return code

DSI RX:
VC
DT
response length
ACK/Error bits

Video:
pixel DT
word count per line
frame/line error count

Error:
ECC single
ECC multi
CRC
timeout
invalid DT
invalid VC
```

初始化命令调试时尤其建议记录：

```text
[12.314 ms] LP DCS SW  cmd=0x11 ret=0
[132.580 ms] LP DCS SW cmd=0x29 ret=0
```

不要只打印：

```text
init ok
```

这种日志的信息密度和“出问题了”差不多。

---

## 第五章、面板控制：DCS、Generic、读回、TE 与低功耗

> **本章解决的工程决策**：厂商初始化表里的每一行到底是什么；哪些命令属于标准 DCS，哪些是厂商私有配置；读操作怎样完成；Sleep、Display Off、ULPS 分别控制什么。
>
> 本章的目标不是背命令码，而是能把初始化表拆成“可解释的状态机”。

### 5.1、DCS 与 Generic：不要简单理解成“标准”和“私有”

DCS：

```text
Display Command Set
```

它定义标准显示控制命令，例如：

```text
Sleep In / Out
Display Off / On
Address Window
Memory Write
Pixel Format
TE
Read Status
```

Generic Packet 则提供通用参数传输机制。

实际 Panel 初始化表里可能同时存在：

- 标准 DCS command；
- 厂商扩展寄存器；
- Page Select / Command Set Select；
- Generic Short/Long Write；
- DCS Long Write 承载厂商定义参数。

因此：

> “厂商私有寄存器一定用 Generic Write”并不是通用规则。

判断一行数据真正是什么，需要同时知道：

1. Host API 调用的是 Generic 还是 DCS；
2. Packet Data Type；
3. Panel Programming Guide 如何定义该命令。

单看首字节 `0xB0/0xFF` 不足以判断传输类型。

---

### 5.2、常用 DCS 命令速查

| Command | 名称 | 典型作用 | 常见注意点 |
| ---: | --- | --- | --- |
| `0x00` | NOP | 空操作 | 常用于占位/特殊时序 |
| `0x01` | Software Reset | 软件复位 | 复位后通常需要等待 |
| `0x04` | Get Display ID | 读显示 ID | Panel 未必实现 |
| `0x09` | Get Display Status | 读状态 | 返回格式看 DCS/Panel |
| `0x0A` | Get Power Mode | 读电源/显示状态 | 很适合 Bring-up |
| `0x10` | Enter Sleep Mode | 进入睡眠 | 与 D-PHY ULPS 不同 |
| `0x11` | Exit Sleep Mode | 退出睡眠 | 后续等待时间必须按规格 |
| `0x28` | Set Display Off | 关闭显示输出 | 不一定等于断电 |
| `0x29` | Set Display On | 开启显示输出 | 通常晚于主要配置 |
| `0x2A` | Set Column Address | 设置 X 地址窗口 | Command Mode 常用 |
| `0x2B` | Set Page Address | 设置 Y 地址窗口 | Command Mode 常用 |
| `0x2C` | Write Memory Start | 开始写 GRAM | 后续为像素数据 |
| `0x2E` | Read Memory Start | 读 GRAM | 是否支持看 Panel |
| `0x34` | Set Tear Off | 关闭 TE 输出 | |
| `0x35` | Set Tear On | 开启 TE 输出 | 参数含 TE mode |
| `0x36` | Set Address Mode | 扫描/翻转/RGB-BGR 等 | 不同 Panel 的实际支持项需确认 |
| `0x3A` | Set Pixel Format | 设置像素格式 | 必须和 DSI pixel format 匹配 |
| `0x3C` | Write Memory Continue | 继续写 GRAM | Command Mode |
| `0x44` | Set Tear Scanline | 设置 TE scanline | 可选能力 |

---

### 5.3、Pixel Format 不是只改一个地方

常见 DCS Pixel Format 参数：

```text
RGB565 → 0x55
RGB666 → 0x66
RGB888 → 0x77
```

但一条完整链路通常至少有这些相关配置：

```text
Framebuffer Format
      ↓
Display Controller Input Format
      ↓
DSI Host Pixel Format
      ↓
DSI Pixel Stream DT
      ↓
Panel DCS Pixel Format
      ↓
Panel Internal Format
```

如果只改其中一个：

- 可能颜色错；
- 可能字节错位；
- 可能一行长度不一致；
- 可能直接不显示。

所以“RGB888”不是一个孤立寄存器，而是一条格式契约。

---

### 5.4、DCS Short Write 与 Long Write 怎样选

以 DCS 为例：

#### 没参数

例如：

```text
0x11 Sleep Out
```

使用：

```text
DT 0x05
DCS Short Write, 0 param
```

#### 一个参数

例如：

```text
0x3A 0x77
```

使用：

```text
DT 0x15
DCS Short Write, 1 param
```

#### 多个参数

例如设置地址窗口：

```text
0x2A
x_start_MSB
x_start_LSB
x_end_MSB
x_end_LSB
```

通常使用：

```text
DT 0x39
DCS Long Write
```

很多 Host API 会根据 buffer length 自动选择 DCS Short/Long Packet。

Linux DRM 中的 `mipi_dsi_dcs_write_buffer()` 就是这种思路。

---

### 5.5、初始化表应该怎样读

假设看到：

```text
{0x11},
delay 120,
{0x3A, 0x77},
{0x29}
```

正确的阅读方式不是：

```text
发 11
等 120
发 3A77
发 29
```

而是：

```text
0x11:
  DCS Exit Sleep Mode
  ↓
等待：
  Panel 内部电路从 sleep 恢复
  等待值必须依据 Panel/DCS timing
  ↓
0x3A 0x77:
  Set Pixel Format = 24-bit
  ↓
0x29:
  Set Display On
```

如果还有：

```text
0xFF ...
0xB0 ...
0xB6 ...
```

必须去 Panel Programming Guide 查：

- page select；
- power；
- gamma；
- GIP；
- VCOM；
- porch internal setting；
- lane/format；
- vendor command unlock；

不能靠命令码长相推测。

---

### 5.6、不要随便删厂商初始化表中的延时

延时通常来自几类需求：

1. Power rail 稳定；
2. Reset 脉宽；
3. Reset release 后内部状态机启动；
4. Sleep Out 后模拟/时钟模块恢复；
5. Display On 前数据路径准备；
6. 厂商私有寄存器的 apply 时间。

最危险的优化方式：

```text
“120 ms 看起来太保守，改 10 ms 也能亮。”
```

室温下一台样机能亮，不代表：

- 低温；
- 高温；
- 慢上电；
- 电源纹波；
- 不同批次 Panel；

都能亮。

只有满足以下条件才能合理缩短：

```text
Datasheet 给出更小 min
+ 实测覆盖 PVT
+ 有足够量产 margin
```

---

### 5.7、典型上电状态机

通用思路：

```text
Power Rails Enable
      ↓
等待 rail 稳定
      ↓
Assert RESET
      ↓
满足 reset low width
      ↓
Deassert RESET
      ↓
等待 Panel internal ready
      ↓
DSI Host / D-PHY 初始化
      ↓
Data Lane / Clock Lane 进入合法 Stop State
      ↓
发送 LP/Command 初始化
      ↓
Exit Sleep
      ↓
等待 datasheet 要求时间
      ↓
其它必要配置
      ↓
Set Display On
      ↓
开始 Video / Memory Write
      ↓
最后开 Backlight
```

实际顺序可能由 Panel 定义成：

```text
Host PHY 先起
```

或：

```text
Panel Reset 先释放
```

所以只能把这个作为结构，不是跨面板照抄的固定毫秒脚本。

---

### 5.8、为什么建议背光最后开

假如一上电就开背光，而 Panel 还没有有效图像：

可能看到：

- 白屏；
- 灰屏；
- 瞬闪；
- 随机花纹。

这容易让人误判 Panel 已经进入异常状态。

Bring-up 时更干净的策略：

```text
Panel/DSI 初始化
→ 首帧稳定
→ Backlight Enable
```

如果背光由 Panel DCS 控制，则按 Panel 的标准流程。

如果由独立 PWM/PMIC 控制，则它属于另一个控制路径。

---

### 5.9、读操作的完整链路

Host 读 Panel，不是发完一个 `0x04` 就神奇地从线里长出 ID。

典型过程：

```text
Host 拥有总线
   ↓
必要时 Set Maximum Return Packet Size
   ↓
发送 DCS/Generic Read Request
   ↓
Host 发起 BTA
   ↓
Data Lane 0 方向反转
   ↓
Panel 在 LP reverse direction 返回 Packet
   ↓
Host 接收
   ↓
Panel 归还总线控制权
```

重点：

- 多 Lane 系统反向传输仍走**物理 Data Lane 0**；
- Peripheral-to-Processor reverse signaling 使用 LP；
- 其它 Data Lane 在该反向事务中不承担返回数据。

---

### 5.10、BTA 是什么

BTA：

```text
Bus Turn-Around
```

它是 D-PHY/DSI 双向控制机制。

因为正常显示时：

```text
Host → Panel
```

是主方向。

当 Host 要读取 Panel：

```text
Host 先明确释放总线控制权
Panel 再获得 Lane 0 的发送权
```

完成后 Panel 再把控制权交回 Host。

如果双方同时驱动，可能出现：

```text
Contention
```

因此 Host 常见错误寄存器里会有：

- BTA timeout；
- contention；
- LP RX timeout。

---

### 5.11、为什么读 ID 成功很有价值，但证明不了全部链路

如果成功读回一个可信的 ID，至少说明了很多东西：

```text
Panel 有电
RESET 大概率已释放
LP Host→Panel 可用
Read Request 能到 Panel
BTA 能发生
Panel Lane0 LP TX 可用
Host Lane0 LP RX 可用
协议/VC 基本匹配
```

这是非常强的自检。

但它**不能证明**：

```text
HS 500/1000 Mbps 稳定
Pixel Stream DT 正确
Video timing 正确
CRC 不出错
所有 Lane 都正常
Framebuffer 格式正确
```

所以：

> “ID 能读回来，因此 MIPI 硬件肯定没问题。”

这个结论范围太大。

---

### 5.12、为什么有些屏读不回，不等于坏了

可能原因：

- Panel 本身是单向 Video peripheral；
- 对应 DCS Read 没实现；
- Board 没把 bidirectional Lane 能力正确接通；
- Host IP 当前模式不支持 BTA；
- VC 错；
- Maximum Return Packet Size 配置错误；
- Panel 还没退出 reset/sleep；
- LP timing 错；
- Lane 0 问题。

因此“读 ID”是优秀的诊断手段，但不能被提升为每块屏必须通过的宗教仪式。

---

### 5.13、Command Mode 的地址窗口与写 GRAM

典型局部更新：

```text
0x2A Set Column Address
x0
x1

0x2B Set Page Address
y0
y1

0x2C Write Memory Start
pixel data...
```

例如更新：

```text
x = 100 ~ 199
y = 200 ~ 299
```

区域：

```text
100 × 100
```

后续只需要发送这一区域的像素。

再次更新连续数据时，某些 Panel 可用：

```text
0x3C Write Memory Continue
```

具体行为以 Panel/DCS 实现为准。

---

### 5.14、TE 的配置链

如果 Panel 使用外部 TE：

```text
DCS Set Tear On
      ↓
Panel TE pin
      ↓
SoC GPIO interrupt / DSI host TE input
      ↓
等待 TE event
      ↓
开始 Memory Write
```

要确认：

- TE polarity；
- pulse width；
- V-blank only 还是包含 H-blank；
- 是 GPIO 还是 Host hardware TE；
- 触发后允许延迟多少；
- Panel 的扫描方向是否影响 tear line。

如果 Host 收到了 TE，但每次都在错误的时刻开始大块 DMA，一样可能撕裂。

---

### 5.15、Sleep、Display Off 与 ULPS 是三件事

#### `0x28 Display Off`

Panel 显示输出关闭。

不代表：

- Panel 断电；
- DSI PHY 进入 ULPS；
- Panel 进入 Sleep。

#### `0x10 Enter Sleep Mode`

DCS 面板低功耗状态。

Panel 内部电路会根据 DCS 规范和器件实现关闭部分功能。

#### ULPS

```text
Ultra-Low Power State
```

属于 D-PHY Lane 状态。

它描述：

- Data Lane；
- Clock Lane；

进入极低功耗电气状态。

因此：

```text
Panel Sleep
≠
D-PHY ULPS
```

它们可以在完整系统 suspend 流程中配合，但不是同一个开关。

---

### 5.16、一个更可靠的 suspend/resume 思路

具体命令看 Panel，但逻辑层级可以这样拆：

#### Suspend

```text
停止送新帧
↓
必要时 Display Off
↓
必要时 Enter Sleep
↓
等待 Panel 规定时间
↓
Host 停止 HS transaction
↓
D-PHY 进入 LP/ULPS
↓
按 Panel 要求关闭电源 rail
```

#### Resume

```text
恢复电源
↓
满足 Power/Reset timing
↓
D-PHY 退出 ULPS / 回到 Stop State
↓
恢复 Panel 命令状态
↓
Exit Sleep
↓
恢复必要寄存器
↓
Display On
↓
恢复画面
```

很多 Panel 在彻底掉电后不会保存初始化寄存器。

因此 Resume 不能想当然地只发：

```text
0x11
0x29
```

---

### 5.17、教学初始化表示例

> 注意：下面只演示“如何注释初始化表”，不是任何真实 Panel 的可执行 init sequence。

```text
1. Power rails stable
2. RESET low/high
3. Wait t_reset_release
4. [Vendor page/unlock sequence]   ← 以 Panel 文档为准
5. [Vendor power/timing/gamma]     ← 以 Panel 文档为准
6. DCS 0x3A, 0x77                 ← RGB888
7. DCS 0x11                       ← Exit Sleep Mode
8. Wait t_sleep_out               ← Datasheet
9. DCS 0x29                       ← Display On
10. Start Video
11. Enable Backlight
```

如果是 Command Mode + TE：

```text
+ DCS 0x35
+ TE hardware config
+ Set address window
+ Memory Write
```

---

### 5.18、初始化表建议转换成结构化数据

不要只保存：

```c
uint8_t init[] = {...};
```

更推荐：

```c
enum dsi_cmd_type {
    DSI_CMD_DCS,
    DSI_CMD_GENERIC,
    DSI_CMD_DELAY_MS,
};

struct panel_cmd {
    enum dsi_cmd_type type;
    const uint8_t *data;
    uint16_t len;
    uint16_t delay_ms;
};
```

至少能明确：

- 传输类型；
- 数据长度；
- 延时。

调试日志也更容易打印：

```text
DCS LONG cmd=0xB0 len=5
GENERIC LONG first=0xFF len=6
DELAY 120 ms
```

---

### 5.19、如何判断一条命令能不能删

必须回答三个问题：

1. 它是 DCS 标准命令还是 vendor command？
2. Panel 上电默认值是什么？
3. 删除后是否在 PVT/重新上电/ESD recovery 下仍稳定？

如果只知道：

```text
删了以后实验室那块屏还能亮
```

只能证明：

```text
当前这一次初始化没有立刻失败
```

不能证明命令冗余。

---

## 第六章、Bring-up 最小路径：从规格书到稳定首帧

> **本章解决的工程决策**：拿到一块新 Panel 时，按照什么顺序做，才能让每一步都有明确通过标准，并且失败后知道下一步查哪里。
>
> 核心原则只有一句：
>
> **先证明基础链路，再证明 Panel 状态，最后证明视频内容。**

### 6.1、为什么“直接跑完整初始化表”不是最优 Bring-up 方法

厂商 Demo 常常一次完成：

```text
Power
Reset
PHY
Panel Init
Video Timing
Backlight
TE
Low Power
```

如果成功，非常省事。

如果失败，你只知道：

```text
黑屏
```

而不知道问题属于：

- 电源；
- Reset；
- D-PHY；
- LP command；
- Panel init；
- HS video；
- Pixel format；
- Backlight。

Bring-up 的目标不是最快执行完代码。

是最快**缩小问题空间**。

---

### 6.2、Bring-up 前先做一张“事实表”

开始写驱动之前，把 Datasheet 信息抄成结构化表。

#### 电源

```text
IOVCC =
VCI =
AVDD =
AVEE =
Power-on order =
Power-off order =
```

#### Reset

```text
Active level =
Min reset width =
Delay after release =
```

#### DSI

```text
Lane count =
Lane mapping =
Lane rate min/max =
Video/Command =
Video sub-mode =
Clock mode =
VC =
EoTp requirement =
```

#### Timing

```text
HACT =
HSA =
HBP =
HFP =
VACT =
VSA =
VBP =
VFP =
FPS =
```

#### Pixel

```text
Pixel format =
RGB/BGR =
DCS 0x3A requirement =
```

#### Control

```text
Read ID supported =
TE supported =
TE polarity =
Sleep out delay =
Display on sequence =
Backlight control =
```

如果这张表填不完，真正缺的不是代码，是输入资料。

---

### 6.3、Step 0：静态硬件核对

在上电前检查：

- Panel FPC pinout；
- 电源 rail 电压；
- RESET；
- Backlight；
- Clock Lane P/N；
- Data Lane P/N；
- Lane order；
- 是否存在 bridge；
- TE 是否接出；
- I2C/GPIO/PMIC 辅助控制。

尤其确认：

```text
Host Lane0 → Panel Lane0
Host Lane1 → Panel Lane1
...
Clock → Clock
```

不要默认 PCB 原理图一定没有 Lane swap。

如果硬件做了合法 lane swap/polarity inversion，还需要 Host PHY 支持并正确配置。

---

### 6.4、Step 1：只验证电源与 Reset

目标：

> Panel 进入一个可预期的上电后状态。

检查：

- rail 实际电压；
- rail 上升顺序；
- reset pulse；
- release 后等待；
- 背光先保持关闭。

通过标准：

```text
所有 rail 在规格范围
reset 波形满足 datasheet
无明显过流
```

失败：

```text
先停在电源层
```

不要去改 HFP。

---

### 6.5、Step 2：启动 DSI Host 与 D-PHY，但先不送视频

配置：

- Lane 数；
- target Lane Rate；
- escape clock；
- D-PHY timing；
- continuous clock（若 Panel 支持，作为 Bring-up 简化项）；
- LP command path。

检查 Host：

```text
PLL lock = 1
PHY ready = 1
stop state = expected
```

具体寄存器名因 SoC 而异。

如果控制器提供：

```text
stopstateclklane
stopstatedata0...
```

应确认 Lane 进入合法 Stop State。

---

### 6.6、Step 3：验证 LP Command Path

发送一个副作用最小、Panel 明确支持的命令。

如果 Panel 支持读回，优先做：

```text
Read Display ID
或
Get Power Mode
```

如果不支持读回，可以先发送：

```text
NOP
Software Reset
```

但“发送成功”只代表 Host transaction 完成，不一定证明 Panel 正确接收。

因此有读回能力时诊断价值更高。

---

### 6.7、Step 4：读回双向链路

如果 Panel 支持：

```text
DCS Read
```

记录：

```text
TX DT
RX DT
RX length
RX payload
ACK/error report
BTA timeout
LP RX timeout
```

#### 通过

返回值：

- 长度合理；
- ID/状态符合 Panel；
- 重复读取稳定。

#### 可疑

- 偶发成功；
- 数据每次不同；
- 有 ECC/BTA timeout；
- 低速能读、高速 command path 不稳。

#### 失败

优先查：

```text
Panel power/reset
VC
Lane0
LP timing
BTA
read command support
return packet size
```

---

### 6.8、Step 5：发送最小初始化表

第一轮不要主动“优化”厂商 init sequence。

保持：

- 命令顺序；
- DCS/Generic 类型；
- 延时；
- page select；
- vendor command。

同时打印：

```text
index
type
len
first byte
return
delay
timestamp
```

如果某一条 Host 返回失败，立即停下来定位。

不要：

```text
for (...) {
    send(cmd);
}
print("init done");
```

然后把中间 80 个错误全吞掉。

---

### 6.9、Step 6：确认 Panel 已退出 Sleep 并 Display On

如果支持读：

```text
Get Power Mode
Get Display Status
```

验证 Panel 状态。

如果不能读：

至少确保：

- `Exit Sleep` 后满足等待；
- `Display On` 已成功发送；
- Panel vendor sequence 完成。

注意：

```text
Backlight 亮
```

不等于：

```text
Display On 成功
```

背光和 LCD/OLED 内容路径可能完全独立。

---

### 6.10、Step 7：先送纯色，不要先跑桌面 GUI

第一张图建议：

```text
全黑
全白
全红
全绿
全蓝
```

原因：

#### 全红/绿/蓝

可以快速发现：

- RGB/BGR 交换；
- channel mapping；
- 某些 bit lane 错位；
- pixel format 错。

#### 全白

容易发现：

- 随机 bit error；
- 行缺失；
- 横纹。

#### 全黑

可以辅助判断：

- background leakage；
- 未初始化区域；
- backlight/Panel 状态。

如果第一张图直接跑复杂 UI，颜色错位和 stride 错误会被纹理掩盖。

---

### 6.11、Step 8：再送几何测试图

推荐：

```text
四象限色块
1-pixel 边框
水平/垂直渐变
棋盘格
坐标文字
```

它们分别验证：

| 图案 | 能发现什么 |
| --- | --- |
| 四象限 | RGB、方向、区域 |
| 1-pixel 边框 | active width/height、裁剪、offset |
| 横/竖线 | stride、扫描方向、行错位 |
| 棋盘格 | pixel packing、DMA、bit error |
| 渐变 | 色深、gamma、banding |
| 坐标文字 | mirror/rotate/address mapping |

测试图是仪器之前最便宜的“视觉协议分析仪”。

---

### 6.12、Step 9：检查错误计数，而不是“肉眼看起来没问题”

至少运行：

```text
几十秒 ~ 数分钟
```

读取：

- ECC；
- CRC；
- FIFO underflow；
- SoT；
- timeout；
- PLL unlock；
- contention。

理想状态：

```text
错误计数稳定为 0
```

如果画面正常但 CRC 每秒都在增加：

> 系统不是“基本好了”，只是 Panel 比较能忍。

这种状态到高温、长线、批量板卡时通常会收利息。

---

### 6.13、Step 10：验证动态画面

纯色稳定后再验证：

- framebuffer 连续更新；
- DMA；
- page flip；
- cache coherency；
- tearing；
- underrun。

Video Mode 常见：

```text
FIFO/DMA 跟不上
→ underflow
→ 行破坏/闪屏
```

这不一定是 D-PHY SI 问题。

如果静态 test pattern 由 DSI Host 内部生成完全稳定，而系统 framebuffer 动态输出不稳定，应把怀疑重点往：

- memory bandwidth；
- DMA；
- display controller；
- cache；

移动。

---

### 6.14、Step 11：最后再打开优化项

基础版本稳定以后，逐个启用：

```text
Non-continuous Clock
Burst
ULPS
TE
局部刷新
高刷新率
动态调频
DSC
```

每启用一个特性：

```text
旧配置基线
vs
新配置
```

记录错误计数和功耗。

不要一次打开五个，然后庆祝平均功耗下降 80 mW，同时偶发一天一次黑屏。人类对“偶发”这个词的容忍度总是神秘得惊人。

---

### 6.15、贯穿案例 Bring-up 记录

#### 输入

```text
800×1280 @ 60
RGB888
4 Lane
Non-Burst Sync Event
500 Mbps/lane
Continuous Clock
```

#### 计算

```text
PCLK           = 66.198 MHz
Min Lane Rate  = 397.188 Mbps/lane
Selected       = 500 Mbps/lane
HS Clock       = 250 MHz
Byte Clock     = 62.5 MHz
```

#### Bring-up

```text
[PASS] Power rails
[PASS] RESET
[PASS] D-PHY PLL lock
[PASS] Stop State
[PASS] LP command
[PASS] Read power mode       ← 若教学 Panel 假设支持
[PASS] Init sequence
[PASS] Exit Sleep
[PASS] Display On
[PASS] RGB color bars
[PASS] 1-pixel border
[PASS] 10 min no ECC/CRC
[PASS] dynamic framebuffer
```

这就是一份比“panel lit”更有价值的记录。

---

### 6.16、Bring-up 检查清单

```text
[ ] Datasheet 参数抄全
[ ] Lane mapping 核对
[ ] 电源 rail 正确
[ ] RESET timing 正确
[ ] Backlight 初始关闭
[ ] Lane 数正确
[ ] LaneRate 预算通过
[ ] PLL lock
[ ] Stop State 正常
[ ] LP command 正常
[ ] Readback 正常（如果支持）
[ ] Init table 每条命令有返回
[ ] Sleep Out delay 满足要求
[ ] Display On
[ ] 纯色正确
[ ] 边框/几何图正确
[ ] ECC=0
[ ] CRC=0
[ ] 无 FIFO underflow
[ ] 动态画面稳定
[ ] 温压/速率 margin 已验证
[ ] 最后才启用低功耗优化
```

---

### 6.17、每一步失败后跳去哪里

| 卡点 | 第一优先级 | 重点章节 |
| --- | --- | --- |
| rail/reset 不对 | Power/Board | 6.4、7.2 |
| PHY 不 ready | PLL/D-PHY timing | 3.10、7.3 |
| LP command 失败 | LP/VC/Lane0 | 4、5.9、7.4 |
| Read BTA 失败 | Lane0/BTA/LP RX | 5.9～5.12 |
| Init 成功但黑屏 | Sleep/Display/Video/Backlight | 5、7.5 |
| 色彩错 | Format/BGR/packing | 3.4、4.5、5.3 |
| 图像偏移 | timing/stride/address | 2、7.6 |
| 雪花/闪屏 | CRC/SI/PHY | 4.7、7.7 |
| 高温才坏 | margin | 7.7、7.18 |
| 动态才坏 | FIFO/memory/DMA | 6.13、7.6 |

---

## 第七章、调试闭环：从现象到层级，再到根因

> **本章解决的工程决策**：出现黑屏、花屏、偏色、撕裂、偶发启动失败时，先查什么，什么时候降速，什么时候才值得上高速仪器。
>
> 调试顺序：
>
> **免费证据 → 可控实验 → 低成本测量 → 高成本仪器**

### 7.1、先把 DSI 问题分成七层

```text
L0  Power / Reset
L1  D-PHY State / PLL
L2  DSI Packet / Command
L3  Panel Internal State
L4  Video Timing / Pixel Format
L5  Display Controller / DMA / Memory
L6  Signal Integrity / PVT Margin
```

很多症状会跨层，但这个分类可以阻止排查无边界扩散。

---

### 7.2、L0：Power / Reset

典型症状：

- 完全无响应；
- ID 读不回；
- 上电偶发；
- 冷启动失败、热重启成功；
- 背光亮但 Panel 无状态。

检查：

```text
rail voltage
rail sequence
reset low width
reset release delay
backlight sequence
```

实验：

```text
延长 reset
延长 power stable delay
完全断电重启
```

如果“延长 reset 后 100% 恢复”，就先别去折磨 CRC。

---

### 7.3、L1：D-PHY / PLL / Stop State

检查：

```text
PLL lock
PHY ready
clock stop state
data lane stop state
HS entry/exit error
SoT error
SoT sync error
escape entry error
```

典型原因：

- Lane Rate 对应的 PLL 配错；
- HS_PREPARE/HS_ZERO/HS_SETTLE 等 timing 不合理；
- Clock Lane 未正确启动；
- lane 数错误；
- lane mapping/polarity；
- Panel max/min rate 不满足。

注意：

> D-PHY timing 的寄存器编码因 SoC 不同，必须用当前 PHY 手册的公式。不要从另一颗芯片搬一个 `hs_settle=0x14` 过来。

---

### 7.4、L2：Packet / LP Command / BTA

典型错误：

```text
ECC single/multi
invalid DT
invalid VC
BTA timeout
LP RX timeout
protocol violation
contention
```

排查：

#### Invalid DT

检查：

- Host packet type；
- Pixel Stream DT；
- Panel 支持格式；
- init command API 是否把 DCS 当成 Generic。

#### Invalid VC

检查：

```text
Host VC == Panel VC
```

#### BTA timeout

检查：

- Panel 是否支持 read；
- Lane0；
- LP RX；
- command timing；
- maximum return size；
- Panel 状态。

#### Contention

检查：

- BTA 时序；
- Host/Panel 方向控制；
- PHY 状态机。

---

### 7.5、L3：Panel Internal State

常见情况：

```text
DSI transaction 都成功
错误寄存器也干净
但仍然黑屏
```

这时要确认：

- Panel 是否仍在 Sleep；
- Display On 是否生效；
- vendor page 是否正确；
- pixel format；
- power mode；
- backlight；
- 内部寄存器是否需要重新初始化。

如果支持读回：

```text
Get Power Mode
Get Display Status
Get Pixel Format
```

非常有价值。

---

### 7.6、L4/L5：Video Timing、Pixel Format、Framebuffer

#### 画面整体偏移

优先：

```text
HACT/HBP/HFP
VACT/VBP/VFP
address window
display offset
```

#### 图像斜切/每行错位

优先：

```text
stride
line length
word count
pixel packing
DMA
```

#### 红蓝交换

优先：

```text
RGB/BGR
MADCTL/address mode
display controller swizzle
```

#### 每几个像素重复/错位

优先：

```text
RGB565/RGB666/RGB888 mismatch
packed vs loosely packed
bus format
```

#### 静态图正常、动态闪

优先：

```text
FIFO underflow
memory bandwidth
DMA
cache coherency
page flip synchronization
```

先不要把所有动态问题都归为“高速信号不好”。

---

### 7.7、L6：Signal Integrity / PHY Margin

典型签名：

- 随 Lane Rate 上升明显变差；
- 高温/低温才出现；
- 某块板比另一块板差；
- CRC/ECC 随速率增加；
- 降速后显著改善；
- 偶发雪花/闪屏；
- 触碰 FPC/连接器症状变化。

这时才应重点考虑：

- 差分阻抗；
- FPC/连接器；
- P/N；
- lane skew；
- D-PHY timing；
- 电源噪声；
- ground return；
- signal integrity margin。

---

### 7.8、降速二分：最便宜的高价值实验

假设当前：

```text
LaneRate = 1000 Mbps
```

出现随机 CRC。

尝试：

```text
1000 → 800 → 600 Mbps
```

前提：

- 仍满足显示带宽；
- Host timing 同步重新配置；
- Panel 支持目标速率。

#### 结果 A：越低越稳定

强烈提示：

```text
PHY/SI margin
D-PHY timing
```

#### 结果 B：任何速率都同样错位

更像：

```text
pixel format
timing
stride
packet config
```

#### 结果 C：降到某点以后完全黑

可能是：

- 低于视频所需带宽；
- 低于 Panel/PHY min lane rate；
- PLL 档位不合法。

降速实验不是“解决方案”。

它是分类工具。

---

### 7.9、不要只做“降速”，还可以做这些二分实验

#### Continuous vs Non-continuous Clock

如果：

```text
continuous 稳
non-continuous 偶发失败
```

检查：

- clock lane LP/HS transition；
- T_CLK_PRE/T_CLK_POST 等相关配置；
- Panel 对 non-continuous 的支持。

#### Burst vs Non-Burst

如果只在 Burst 出错：

- burst lane rate；
- line packetization；
- BLLP；
- Panel mode support。

#### Test Pattern vs Framebuffer

如果 Host internal pattern 稳：

```text
DSI/PHY 大概率更健康
```

而 framebuffer 不稳：

```text
Display controller / memory / DMA
```

优先级上升。

#### 冷启动 vs Warm Reset

只冷启动失败：

```text
power/reset timing
```

优先级上升。

---

### 7.10、错误寄存器应该怎样设计日志

不同 SoC bit 位不同，但建议统一成抽象类别：

```text
PHY:
  pll_unlock
  sot
  sot_sync
  eot_sync
  esc_entry

PROTOCOL:
  ecc_single
  ecc_multi
  crc
  invalid_dt
  invalid_vc
  protocol_violation

BIDIR:
  bta_timeout
  lp_rx_timeout
  contention

FLOW:
  tx_fifo_underflow
  tx_fifo_overflow
  rx_fifo_underflow
  rx_fifo_overflow

DISPLAY:
  video_underflow
```

日志中打印：

```text
raw register
decoded error
cumulative count
timestamp
```

例如：

```text
[123.501s] DSI_ERR CRC count=17 raw=0x00000400
```

比：

```text
mipi error
```

强很多。

---

### 7.11、建议的启动日志

```text
[PANEL] power on
[PANEL] reset assert
[PANEL] reset deassert

[DSI] lanes=4
[DSI] mode=video-sync-event
[DSI] format=RGB888
[DSI] vc=0
[DSI] pclk=66.198MHz
[DSI] lane_rate=500Mbps
[DSI] byte_clk=62.5MHz

[PHY] pll lock
[PHY] stopstate clk=1 d0=1 d1=1 d2=1 d3=1

[PANEL] DCS 0x11 ret=0
[PANEL] delay xxx ms
[PANEL] DCS 0x29 ret=0

[VIDEO] start
[VIDEO] first frame
[BACKLIGHT] on
```

如果允许读回：

```text
[PANEL] id=...
[PANEL] power_mode=...
```

启动失败时，这种日志通常已经能把范围砍掉一半。

---

### 7.12、故障签名表

| 现象 | 高概率方向 | 第一实验 |
| --- | --- | --- |
| 完全无反应 | power/reset/PHY | 测 rail/reset，查 PLL/stop state |
| 背光亮、全黑 | Panel state/video/backlight 独立路径 | 读 power mode，送纯色 |
| 全白屏 | Panel 未收有效图/内部默认状态 | 检 init、video start |
| 红蓝交换 | RGB/BGR | 送纯红/纯蓝 |
| 颜色量化异常 | bpp/format | 核 0x3A、DSI DT、FB format |
| 画面水平偏移 | H timing / offset | 1-pixel border |
| 画面垂直偏移 | V timing / page offset | 1-pixel border |
| 每行斜切 | stride/WC/line length | 检 DMA stride、WC |
| 固定横纹 | timing/underflow | 查行周期、FIFO |
| 随机雪花 | CRC/SI | 查 CRC，降速 |
| 偶发闪屏 | PHY margin/power | 错误计数 + 温压 |
| 高温花屏 | margin | 降速/示波 |
| Command 局刷撕裂 | TE/update window | 抓 TE+写入时间 |
| 上电偶发黑屏 | reset/power/init delay | 延长时序、完整掉电 |
| 静态正常动态坏 | DMA/memory bandwidth | internal pattern vs FB |

---

### 7.13、读回分支树

```text
Read ID
  │
  ├─ 成功且稳定
  │    ├─ LP TX 基本 OK
  │    ├─ BTA 基本 OK
  │    ├─ Lane0 reverse LP 基本 OK
  │    └─ 继续查 HS Video
  │
  └─ 失败
       │
       ├─ Host 报 BTA timeout
       │     └─ Lane0 / Panel read support / LP RX
       │
       ├─ ACK Error Report
       │     └─ 解析 error bit
       │
       ├─ 完全无响应
       │     └─ Power / Reset / VC / command path
       │
       └─ 偶发数据错
             └─ LP timing / integrity / state
```

---

### 7.14、什么时候用万用表

适合：

- rail；
- reset 静态电平；
- enable pin；
- backlight supply。

不适合：

- HS D-PHY；
- LP transition timing；
- CRC。

听起来显然，但调试现场总有人拿万用表盯着高速差分线，仿佛它会被耐心感化。

---

### 7.15、什么时候用逻辑分析仪

适合：

- RESET；
- TE；
- GPIO；
- 低速控制；
- 某些足够低速的 LP 状态观察。

不适合：

- 数百 Mbps/Gbps D-PHY HS 差分内容；
- 眼图；
- HS settle 精细测量。

普通数字逻辑分析仪不能因为软件界面里有“1 GHz”字样就自动变成 D-PHY 分析仪。

---

### 7.16、什么时候用示波器

#### 普通单端探头

可以看：

- rail；
- reset；
- TE；
- LP 电平/趋势。

不建议用来直接评价高速 D-PHY 差分质量。

#### 高带宽差分探头 + 合适示波器

可以看：

- HS amplitude；
- transition；
- skew；
- timing；
- eye/margin（在具备相应能力和方法时）。

高速测量本身会引入负载。

探头、带宽、焊接点、参考地都会影响结果。

---

### 7.17、什么时候值得用 D-PHY/DSI 协议分析仪

当你需要知道：

```text
到底发了哪个 Packet
DT 是什么
VC 是什么
WC 是多少
ECC/CRC 是否正确
一帧 packet sequence 是否符合预期
```

协议分析仪价值很高。

特别适合：

- Host 与 Panel 厂商互相认为“对方协议不对”；
- Video Mode packetization 有争议；
- Vendor command 不明确；
- BTA/ACK Error 难查。

它的价值是把：

```text
“波形”
```

提升为：

```text
“协议事件”
```

但在 rail 都没上对的时候就借一台昂贵分析仪，是一种很有预算感的低效率。

---

### 7.18、PVT Margin：点亮不是结束

PVT：

```text
Process
Voltage
Temperature
```

至少做：

- 高温；
- 低温；
- 电源上下限；
- 多块板；
- 多块 Panel；
- 目标最高 Lane Rate；
- suspend/resume；
- 冷启动循环；
- ESD recovery（如果产品要求）。

目标不是：

```text
能亮
```

而是：

```text
在目标工作范围内
错误计数仍保持可接受
并且启动/恢复具有确定性
```

---

### 7.19、一个完整调试案例：随机雪花

#### 现象

```text
室温偶发彩点
高温明显增多
```

#### 免费信息

```text
CRC count 持续增加
ECC 偶发
无 FIFO underflow
```

#### 假设

```text
优先怀疑 HS PHY/SI margin
```

#### 实验 1

```text
LaneRate 900 → 700 Mbps
```

前提仍满足带宽。

结果：

```text
CRC 显著下降
```

#### 实验 2

```text
Continuous Clock
```

结果进一步改善。

#### 下一步

检查：

- D-PHY timing；
- clock/data lane signal；
- FPC；
- impedance；
- power noise；
- panel rate window。

这是一条证据链。

不是：

```text
“感觉 PLL 可能有问题。”
```

---

### 7.20、另一个案例：背光亮但全黑

#### Step 1

读 ID：

```text
成功
```

说明 LP 双向基本成立。

#### Step 2

读 Power Mode：

发现 Panel 仍处于 Sleep 或 Display Off。

#### Step 3

回查：

```text
0x11 后延时被优化掉
```

恢复 datasheet 延时。

Panel 正常。

这个案例说明：

> ID 能读回并不代表 Panel 已进入可显示状态。

---

## 第八章、附录：公式、Data Type、DCS 与易错点速查

> 本章不再引入新的主线知识，只把前七章压缩成项目现场可以直接查的形式。

### 8.1、Video Mode 公式速查

```text
HTOTAL = HACT + HSA + HBP + HFP

VTOTAL = VACT + VSA + VBP + VFP

PCLK = HTOTAL × VTOTAL × FPS

AggregateBW_min = PCLK × bpp

LaneRate_min = AggregateBW_min / Nlane

Fclk_hs = LaneRate / 2

ByteClk = LaneRate / 8
```

注意：

```text
LaneRate_min
```

只是基础理论需求。

真正配置还需检查：

```text
packet overhead
video mode
Host timing
PLL discrete rate
Panel min/max
D-PHY timing
```

---

### 8.2、Command Mode 公式速查

整帧：

```text
FrameBits = Width × Height × bpp
```

区域：

```text
RegionBits = Wregion × Hregion × bpp
```

payload 基础数据率：

```text
RequiredBW_payload
= PayloadBits / AvailableTime
```

单 Lane：

```text
LaneRate_payload
= RequiredBW_payload / Nlane
```

再加入 Host/协议实际开销与 margin。

---

### 8.3、RGB 格式速查

| 格式 | 有效色深 | DSI 典型 DT | 链路基础占用 |
| --- | ---: | ---: | ---: |
| RGB565 | 16 bit | `0x0E` | 16 bpp |
| RGB666 Packed | 18 bit | `0x1E` | 18 bpp |
| RGB666 3-byte | 18 bit | `0x2E` | 24 bit/pixel |
| RGB888 | 24 bit | `0x3E` | 24 bpp |

DCS `Set Pixel Format` 常见参数：

| 格式 | 常见 DCS 参数 |
| --- | ---: |
| RGB565 | `0x55` |
| RGB666 | `0x66` |
| RGB888 | `0x77` |

最终仍以 Panel 实现为准。

---

### 8.4、Packet 速查

#### Short Packet

```text
4 byte
```

结构：

```text
DI | Data0 | Data1 | ECC
```

#### Long Packet

```text
DI | WC_L | WC_H | ECC | Payload | CRC_L | CRC_H
```

总长度：

```text
6 + WC
```

---

### 8.5、ECC / CRC 速查

| 项目 | ECC | CRC |
| --- | --- | --- |
| 保护对象 | Packet Header | Long Packet Payload |
| 能否纠错 | 单 bit header error 可纠正 | 不负责纠错 |
| 典型错误 | ECC single/multi | CRC error |
| 优先排查 | Header/PHY reliability | Payload HS integrity |

CRC 多项式：

```text
x^16 + x^12 + x^5 + 1
```

---

### 8.6、Processor → Peripheral 常用 DT

| DT | 事务 |
| ---: | --- |
| `0x01` | V Sync Start |
| `0x11` | V Sync End |
| `0x21` | H Sync Start |
| `0x31` | H Sync End |
| `0x08` | EoTp |
| `0x09` | Null Packet |
| `0x19` | Blanking Packet |
| `0x03` | Generic SW 0 param |
| `0x13` | Generic SW 1 param |
| `0x23` | Generic SW 2 param |
| `0x04` | Generic Read 0 param |
| `0x14` | Generic Read 1 param |
| `0x24` | Generic Read 2 param |
| `0x29` | Generic Long Write |
| `0x05` | DCS SW 0 param |
| `0x15` | DCS SW 1 param |
| `0x06` | DCS Read |
| `0x39` | DCS Long Write |
| `0x37` | Set Max Return Packet Size |
| `0x0E` | RGB565 |
| `0x1E` | RGB666 Packed |
| `0x2E` | RGB666 3-byte |
| `0x3E` | RGB888 |

---

### 8.7、Peripheral → Processor 常用 DT

| DT | 返回 |
| ---: | --- |
| `0x02` | ACK + Error Report |
| `0x11` | Generic Short Read, 1 byte |
| `0x12` | Generic Short Read, 2 byte |
| `0x1A` | Generic Long Read |
| `0x1C` | DCS Long Read |
| `0x21` | DCS Short Read, 1 byte |
| `0x22` | DCS Short Read, 2 byte |

---

### 8.8、常用 DCS 速查

| Command | 名称 |
| ---: | --- |
| `0x00` | NOP |
| `0x01` | Software Reset |
| `0x04` | Get Display ID |
| `0x09` | Get Display Status |
| `0x0A` | Get Power Mode |
| `0x10` | Enter Sleep |
| `0x11` | Exit Sleep |
| `0x28` | Display Off |
| `0x29` | Display On |
| `0x2A` | Column Address |
| `0x2B` | Page Address |
| `0x2C` | Memory Write Start |
| `0x2E` | Memory Read Start |
| `0x34` | Tear Off |
| `0x35` | Tear On |
| `0x36` | Address Mode |
| `0x3A` | Pixel Format |
| `0x3C` | Memory Write Continue |
| `0x44` | Tear Scanline |

---

### 8.9、模式速记

#### Non-Burst Sync Pulse

```text
强调完整同步 pulse 信息
HSS/HSE
VSS/VSE
```

#### Non-Burst Sync Event

```text
只需要关键 sync event
Panel 重建 timing
```

#### Burst

```text
Pixel data 时间压缩
→ 留出更长 BLLP/LP
```

#### Command Mode

```text
Host 写 Panel GRAM
→ 可全刷/局刷
→ 常结合 TE
```

---

### 8.10、低功耗概念速记

```text
Display Off
    DCS 显示控制

Sleep
    Panel 内部低功耗状态

LP
    D-PHY Low-Power signaling

ULPS
    D-PHY Ultra-Low Power State

Non-continuous Clock
    Clock Lane 可在空闲期回 Stop State
```

它们不是同义词。

---

### 8.11、常见错误说法对照

| 错误说法 | 更准确的说法 |
| --- | --- |
| MIPI 时钟 500 MHz 就是 500 Mbps | D-PHY DDR 下 500 Mbps/lane 对应 HS Clock 约 250 MHz |
| RGB666 一定是 18 bpp 带宽 | Loosely/3-byte RGB666 会占 24 bit/pixel |
| Non-Burst 消隐期必须一直 HS | 时间允许时部分实现可用 LP interval 替代 blanking |
| Burst 一定更省电 | 它创造更多潜在空闲时间，实际功耗取决于 PHY/Panel 策略 |
| Command Mode 没有时序 | 不持续传 DPI raster，但仍有 Panel scan、TE、update window |
| CRC Error 可以自动纠正 | CRC 用于检测 Payload error，不负责恢复错误数据 |
| ECC 能修所有错误 | Header 单 bit 可纠；多 bit 不保证 |
| 读 ID 成功说明所有 Lane 都正常 | 主要验证 LP command、BTA、Lane0 reverse path，不证明 HS video |
| 单屏 VC 必须为 0 | 通常用 VC0，但 Host 与 Panel 一致才是关键 |
| 所有私有命令都用 Generic | 取决于 Panel 定义和 Host API |
| 0x11 后固定必须延时 120 ms | 延时必须以当前 DCS/Panel 规格为准，120 ms 只是常见值 |
| porch 不显示，可以随便减 | porch 是 Panel timing 的组成部分，必须满足 min/typ/max |
| 花屏就是信号完整性 | format、stride、FIFO、timing、PHY 都可能 |
| 降速能修好就结束 | 降速首先是定位 margin 的实验 |
| 背光亮说明 Panel 工作正常 | Backlight 与 Panel data path 可完全独立 |
