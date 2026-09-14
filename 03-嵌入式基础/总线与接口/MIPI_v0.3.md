# MIPI DSI 落地：从选型到量产交付

> **文档定位**：本文聚焦于如何把“已经点亮的一块 DSI 屏”，做成一个可追溯、可验证、可维护、可批量交付的显示产品。
>
> 本文不把“亮屏”当作终点。实验室样机能亮，只能证明某一块板、某一块屏、某一组参数在某个环境下曾经工作过。产品交付需要回答更麻烦、也更现实的问题：为什么选这个方案？硬件是否留有余量？参数由谁维护？换一批屏会不会翻车？高低温、EMC、老化后还能不能工作？最终凭什么签字放行？

---

## 第一章、先看全局：这篇文档到底解决什么

### 1.1、一句话理解本文

一条 DSI 链路完成 bring-up——电源/复位/初始化时序正确、Host 与 Panel 进入预期模式、首帧正常、没有持续增长的协议错误——只是“**功能闭环**”，不是“**工程闭环**”：它证明不了选型是否留有余量、硬件是否可复制、参数是否可维护、问题是否可追溯。

所以本篇的核心不是继续堆 DSI 知识点，而是补上这条工程闭环：

```text
需求
 ↓
方案选型
 ↓
原理图 / PCB 约束
 ↓
PHY 参数与链路裕量
 ↓
软件参数架构
```

**把屏点亮只是起点，本文要回答的是：这套方案凭什么可以被复制、被维护。**

---

### 1.2、四个工程问题与章节地图

后面章节会出现大量 PHY、PCB、Linux DRM 术语，但主线始终只有四个问题，且顺序不能颠倒：选型决定硬件形态，硬件决定电气上限，电气上限限制软件配置，参数架构决定可维护性。

| 工程问题 | 章节 | 最终产出 |
| --- | --- | --- |
| 为什么选这个显示方案？ | 第二章 | 选型论证表 |
| 硬件是否具备稳定工作的基础？ | 第三章 | 原理图与 PCB 评审表 |
| 当前链路还有多少电气与时序余量？ | 第四章 | PHY 参数与裕量表 |
| 软件以后怎么维护多 Panel、多批次？ | 第五章 | 参数归属与变更回归矩阵 |

这四份产出物不是“附带表格”，而是本文真正的骨架：正文所有知识点都应该能落回其中一项，否则大概率只是知识点收藏癖发作，对交付没有帮助。

**读法**：第一次学习建议顺读；项目评审时按上表反查（选型存疑→第二章，硬件评审→第三章，PHY 裕量存疑→第四章，多 Panel 维护→第五章）。

---

### 1.3、贯穿案例：800×1280 Panel 从样机到产品

本文使用同一块教学用 800×1280 Panel 贯穿全文计算与举例，场景是真实产品化问题：批量交付、两家 Panel 供应商、明确的工作温度范围、EMC 相关验证。SoC 与 Panel 的具体型号、porch、刷新率上限、电压、PHY 版本等，必须从实际规格书填写，不在本文虚构。

仅为演示带宽关系，临时假设 60 Hz、RGB888、4 条 D-PHY Data Lane，得到**有效像素理论下限**：

```text
800 × 1280 × 60 × 24 bit = 1.47456 Gbit/s（四条 Lane 合计的有效像素数据）
1.47456 / 4 = 368.64 Mbit/s/Lane
```

这个 368.64 Mbit/s **绝不能直接拿去配置 PHY**：它还没有计入水平/垂直 blanking、DSI 包头与 CRC/ECC 等协议开销、Video Mode 的具体传输方式、Host 控制器时钟粒度和设计裕量。真实 lane rate 仍应按 Panel timing、工作模式和控制器约束重新计算；这里故意只给下限，提醒一个常见事故：**算出一个数字，不代表那个数字就是寄存器值。**

---

## 第二章、接口与方案选型：先证明“为什么这样做”

> **本章解决的工程决策**：确认 DSI 是正确方案，并冻结 PHY 类型、DSI/DSI-2 能力边界、Lane 数、工作模式和压缩策略。

### 2.1、接口准入：不要先爱上某个接口再给它找理由

显示接口选择应从产品需求反推，而不是“这个 SoC 正好有 DSI，所以用 DSI”。

| 接口 | 典型优势 | 主要代价 | 更适合什么情况 | 本项目评审重点 |
| --- | --- | --- | --- | --- |
| MCU/RGB 并口 | 协议简单、时序直观 | 引脚多、布线多、EMI 压力明显 | 中低分辨率、板内直连 | 引脚是否可接受 |
| SPI/QSPI 类显示 | 引脚少、控制简单 | 像素吞吐有限，高刷新困难 | 小尺寸、低刷新、GUI/仪表 | 是否满足刷新和交互 |
| MIPI DSI | 引脚少、带宽高、低功耗生态成熟 | PHY/时序/调试复杂度高 | 嵌入式中高分辨率 Panel | SoC/Panel 双侧能力是否匹配 |
| LVDS | 产业成熟、链路直观 | 线对较多，移动/小型 SoC 生态不一定合适 | 工控、中尺寸传统 Panel | SoC 是否原生支持 |
| eDP | 高带宽、PC/大屏生态强 | 协议栈与 PHY 复杂度较高 | 笔记本、较高分辨率大屏 | SoC/eDP bridge 成本 |

这里不应该写死“某接口支持多少 Mbps 就一定适用”，因为真正上限受：

- PHY 版本；
- Lane 数；
- 控制器实现；
- PCB/FPC 通道；
- Panel 接收能力；
- 工作模式；
- 产品 EMI/功耗约束。

**本项目只有在 SoC 和两家 Panel 都能给出明确 DSI 能力、所需带宽可在额定范围内满足、并且针脚/功耗/成本优于替代方案时，才应该正式冻结为 DSI。**

---

### 2.2、D-PHY 与 C-PHY：选的是系统能力，不是名词新旧

#### 2.2.1、先纠正一个常见过度简化

经典 D-PHY 采用：

- 一条独立 Clock Lane；
- 一条或多条 Data Lane；
- HS 使用低摆幅差分传输；
- LP 使用单端状态完成控制、状态切换等工作。

但这不是“D-PHY 永远如此”。D-PHY v3.5 开始提供**可选 embedded-clock 模式**。因此项目文档必须写清实际使用的 D-PHY 版本和模式，不能只写一句“D-PHY”。

本文后续涉及 Clock Lane、Clock/Data skew 的内容，默认指大多数现有嵌入式 DSI 项目采用的 **forwarded-clock D-PHY**。

#### 2.2.2、D-PHY 与 C-PHY 的工程差异

| 维度 | D-PHY | C-PHY |
| --- | --- | --- |
| 基本信号组织 | 传统模式为 Clock Lane + Data Lane | 每个 Lane 是三根线组成的 trio |
| 时钟 | 传统模式转发独立时钟；新版本可有 embedded-clock | embedded clock |
| 编码 | HS 差分 bit 传输 | 三相符号编码，约 2.28 bit/symbol |
| 引脚效率 | 取决于 Lane 数与 PHY 版本 | 同等线数下通常可获得更高编码效率 |
| PCB 规则 | 差分对 + 时钟/数据偏斜管理 | trio 的单端阻抗、线间关系与 skew 规则不同 |
| 项目风险 | 生态成熟，但仍需确认具体 SoC/Panel 版本 | 必须确认 SoC、Panel、连接器和工具链是否真正支持 |

**不能把 C-PHY 理解成“更快，所以一定更好”。**如果 SoC 只有 D-PHY、Panel 只有 D-PHY，或者项目工具链、测试能力、供应链已经围绕 D-PHY 建立，协议层面再先进也没有现实意义。

#### 2.2.3、选型时真正要填的不是“D-PHY/C-PHY”四个字

至少应记录：

```text
Host 支持：____________________
Panel A 支持：_________________
Panel B 支持：_________________
PHY 版本：____________________
工作模式：forwarded / embedded clock
最大额定速率：________________
需要的实际速率：______________
验证工具是否支持：____________
最终结论：____________________
```

---

### 2.3、DSI 与 DSI-2：不要把协议版本和 PHY 版本混成一件事

截至 2026 年，MIPI 官方仍同时维护传统 **MIPI DSI** 与 **MIPI DSI-2** 两套规范体系。工程上需要特别注意：

- MIPI DSI 当前公开版本线为 v1.3.x，工作在 D-PHY 上；
- DSI 本身已经纳入 VESA DSC，不能简单写成“只有 DSI-2 才支持 DSC”；
- DSI-2 是更新的显示协议体系，可配合 D-PHY、C-PHY，并支持面向更高带宽和更新显示能力的扩展；
- DSI-2 还纳入 DSC、VDC-M 等压缩能力；
- “SoC 宣称支持 DSI”并不等于“支持最新 DSI-2 + 最新 D-PHY”。很多量产 SoC 使用的是更早的控制器和 PHY IP。

所以版本确认必须分成至少三层：

```text
显示协议：DSI / DSI-2，版本 ______
物理层：D-PHY / C-PHY，版本 ______
Host IP 实际支持能力：____________
Panel/DDIC 实际支持能力：__________
```

最终取双侧能力交集，而不是拿最新规范版本替老芯片许愿。

---

### 2.4、什么时候才应该考虑 DSC

DSC 的正确定位是：**当未压缩链路在合理 Lane 数和额定速率内无法满足目标显示模式时，用压缩换带宽。**

判断顺序建议固定为：

```text
1. timing / bpp / 刷新率是否真的算对？
      ↓
2. Lane 数能否增加？（硬件约束见 2.5.3）
      ↓
3. 能否在 Panel 允许范围内调整像素格式或工作模式？
      ↓
4. Host 和 Panel 是否都支持更高额定 lane rate？
      ↓
5. 仍然不够，再评估 DSC
```

启用 DSC 后会新增：

- Host 与 Panel 双侧 DSC 能力匹配；
- slice、bits-per-pixel、PPS 等配置；
- 驱动对象和参数；
- 抓包/调试复杂度；
- 多供应商兼容限制；
- 回归矩阵中的压缩开关、异常恢复、画质与带宽验证。

“视觉无损”也不是“数学上无损”。产品如果对图像链路有特殊验证要求，必须由显示/画质团队定义可接受判据。

---

### 2.5、Lane 数怎么从需求反推

#### 2.5.1、先算理论下限

Video Mode 下，最基础的有效像素数据量为：

```text
Active_Bitrate = Hactive × Vactive × FPS × bpp
```

如果使用 N 条 Data Lane，则理想情况下：

```text
Active_Lane_Rate = Active_Bitrate / N
```

但真实配置不能停在这里。

#### 2.5.2、真实链路还必须加入 timing 和协议因素

对于连续 Video Mode，更常见的估算入口是：

```text
PixelClock = Htotal × Vtotal × FPS

RawPixelRate ≈ PixelClock × bpp

RawLaneRate ≈ RawPixelRate / N   （N 与 2.5.1 中的 Data Lane 数一致）
```

随后再根据：

- Non-Burst / Burst；
- Sync Pulse / Sync Event；
- 包协议开销；
- blanking 是否实际以 HS 数据占用；
- 控制器 lane-rate/byte-clock 分频能力；

得到 Host 允许的目标 PHY rate。

不同控制器的寄存器可能叫：

- lane rate；
- bit clock；
- byte clock；
- PHY clock；
- PLL output；

它们的单位和倍频关系不一定相同。**看到“500 MHz”绝不能自动理解成“500 Mbps/Lane”。**

#### 2.5.3、Lane 数不是纯软件参数

它同时被四方约束：

1. SoC 有多少物理 Lane；
2. Panel 接收端支持几条 Lane；
3. PCB/FPC/连接器是否真正连出这些 Lane；
4. 两家供应商是否能共用同一拓扑。

如果 Panel A 支持 4 Lane、Panel B 只支持 2 Lane，最终“兼容两家供应商”就可能迫使系统统一到双方交集，或者为不同硬件版本付出代价。

---

### 2.6、选型论证表模板

| 项目 | 决策 | 依据 | 硬件前提 | 备选方案 | 切换代价 |
| --- | --- | --- | --- | --- | --- |
| 显示接口 | DSI | 带宽、针脚、SoC/Panel 支持 | DSI Host + 对应 FPC | eDP bridge / LVDS 等 | 原理图、BOM、驱动变化 |
| PHY | D-PHY / C-PHY | Host 与两家 Panel 能力交集 | PCB 按对应 PHY 布线 | 另一 PHY | 基本等同重做链路 |
| 协议版本 | 实际 IP 版本 | SoC TRM + DDIC Spec | 无 | 无 | 受 IP 限制 |
| Data Lane 数 | 1/2/3/4/... | 带宽计算 + 双侧能力 | 连接器/FPC 已连出 | 调整 FPS/bpp/压缩 | 性能或硬件代价 |
| 工作模式 | Video / Command | Panel/DDIC + 产品需求 | TE/帧缓存能力 | 另一模式 | 驱动和功耗模型变化 |
| DSC | 开/关 | 未压缩带宽是否满足 | Host + Panel 双侧支持 | 增 Lane / 降速率需求 | 调试和供应链复杂度增加 |

---

## 第三章、原理图与 PCB 评审：先保证物理链路没有先天缺陷

> **本章解决的工程决策**：硬件是否满足 DSI 稳定工作的前提，哪些问题必须在投板前关闭，哪些可以带条件进入样机阶段。

### 3.1、评审表应该长什么样

推荐列至少包含：

| 字段 | 含义 |
| --- | --- |
| 条目 | 检查对象 |
| 要求 | 为什么要检查 |
| 检查方法 | 看原理图、PCB、仿真、规格书还是实测 |
| 通过判据 | 什么情况可以签字 |
| 失效表现 | 不满足时最可能看到什么 |
| 责任方 | HW / PCB / SI / SW / Panel 厂 |
| 状态 | Pass / Conditional / Fail |
| 证据 | 原理图页码、截图、仿真报告、示波器记录 |

评审的关键不是“大家开会看过了”，而是未来出问题时能回头知道：**当时基于什么证据接受了这个设计。**

---

### 3.2、电源、复位和背光时序

Panel 常见资源包括：

- I/O 电源；
- 模拟/驱动电源；
- 正负压偏置；
- Reset；
- Backlight Enable/PWM；
- 有时还包含 Touch、Bridge、EEPROM 等附属器件。

不能用“先上 3.3 V，再拉高 Reset”这种模板覆盖所有 Panel。正确顺序应来自：

```text
Panel Datasheet / DDIC Datasheet
        ↓
原理图电源实现是否做得到
        ↓
软件 prepare/unprepare 是否严格实现
        ↓
示波器确认实物时序
```

#### 3.2.1、Reset 释放

检查：

- Reset 默认电平是否确定；
- 上电时 GPIO 是否会浮空；
- 电源稳定到 Reset 释放之间是否满足 Panel 要求；
- Linux probe 较晚时，Bootloader 是否已经改变过 Reset；
- 热重启与冷启动的路径是否不同。

#### 3.2.2、背光

多数 LCD 项目中，背光通常应在：

1. Panel 电源稳定；
2. 初始化完成；
3. 视频链路稳定；
4. Panel 已进入 Display On；

之后再打开。

关机顺序通常相反，优先灭背光再停止图像和断电，可以避免白闪、随机画面和电源掉落时的残影。

但这仍然是**常见策略，不是替代 Panel Spec 的绝对规范**。

---

### 3.3、D-PHY 高速线：阻抗、偏斜和参考平面

#### 3.3.1、D-PHY 不只是“差分线”

在传统 D-PHY 中，同一组线：

- HS 阶段按低摆幅差分工作；
- LP 阶段又按单端状态工作。

因此 PCB 设计通常既关心 differential impedance，也关心 single-ended impedance。

很多 SoC 厂商给出的典型设计目标是约：

```text
100 Ω differential
50 Ω single-ended
```

例如 ST 的部分 DSI 设计指南给出 100 Ω 典型差分阻抗，并给出 ±10% 级别示例窗口；这类值可以作为理解参考，但**项目约束必须以实际 SoC/PHY Hardware Design Guide 为准**。

#### 3.3.2、对内等长与对间等长不是一回事

- **P/N 对内 skew**：影响差分信号本身的叠加与共模转换，通常要求更严。
- **Data Lane 之间、Clock 与 Data 之间 skew**：影响接收采样窗口和 deskew 负担。

不同 PHY 版本、速率和 SoC 封装会给出不同约束，因此不能把网络上某个“5 mil”数字复制到所有设计。

一个合理评审表应该写：

```text
P/N 最大允许 skew：来自 SoC Design Guide 第 ___ 页
Clock/Data 最大允许 skew：来自 ______
是否包含 SoC package delay：是 / 否
PCB 实际 worst case：________
结论：Pass / Fail
```

#### 3.3.3、参考平面必须连续

重点检查：

- 不跨 GND split；
- 不跨 plane slot；
- 不在参考平面突然变成另一电源岛；
- 换层时有合理的回流过孔；
- P/N 换层结构尽量对称。

高速信号真正传播的是“信号 + 返回路径”，不是 PCB 上那条漂亮的绿色线。只看走线长度，不看回流路径，是一种非常高效的返板方式。

---

### 3.4、长度、拓扑、FPC 与连接器

#### 3.4.1、优先点到点

DSI/D-PHY 是典型点到点高速链路。评审时应重点排除：

- T 型分支；
- 为了方便测量留下很长测试 stub；
- 连接器之后又分叉到两块 Panel；
- DNP 器件焊盘形成显著支路。

#### 3.4.2、总长度不能脱离 PHY 版本和通道模型单独规定

“DSI 最长只能 10 cm”这类说法不具备通用性。真实允许长度取决于：

- lane rate；
- PCB 材料损耗；
- FPC 损耗；
- 连接器；
- PHY 版本；
- TX/RX equalization 能力；
- 通道插损与反射。

因此项目应记录的是**通道预算来源**，不是背一个固定厘米数。

#### 3.4.3、FPC 和连接器也属于高速通道

至少检查：

- 是否有厂家阻抗规格；
- GND pin 是否足够并形成合理回流；
- 差分对/三线 trio 的 pin mapping 是否连续；
- FPC 折弯后的阻抗变化是否可接受；
- 插拔寿命和接触电阻是否满足产品要求；
- 两家 Panel 的 FPC pinout 是否真正兼容，而不只是“针脚数一样”。

---

### 3.5、ESD：不是“加个 TVS 就更安全”

高速线上 ESD 器件会引入：

- 寄生电容；
- insertion loss；
- 阻抗不连续；
- P/N 不匹配；
- 高频下的非线性效应。

因此不应该用普通低速 TVS 直接替代经过高速接口验证的器件。

正确的器件选择顺序：

```text
目标 ESD 等级
  ↓
实际最高 lane rate
  ↓
器件厂家是否明确标注适用 MIPI D-PHY/C-PHY 或对应高速率
  ↓
查看 Cj / S 参数 / insertion loss / channel count
  ↓
确认布局参考设计
  ↓
SI + ESD + EMC 实测
```

不要追求一个“所有 MIPI 都必须小于 0.x pF”的万能数字。高速率越高，允许的附加电容和不连续通常越敏感；最终判据应该是通道和眼图是否仍满足系统要求。

布局上通常要求 ESD 器件靠近外部连接器/进入点，并让放电路径短而直接回到合适地参考，避免先让 ESD 电流在板上旅行一圈再想起地在哪里。

---

### 3.6、串阻、共模扼流圈与 EMI 预留

#### 3.6.1、串阻不是 DSI 的默认配置

D-PHY 本身已经有受控输出阻抗和接收端终端机制。未经验证直接增加串联电阻可能：

- 降低 HS 振幅；
- 改变边沿；
- 引入新的反射；
- 同时影响 LP 与 HS 行为。

因此原则应写成：

> **默认不因为“高速接口习惯”而添加串阻；只有 SoC/PHY 厂商参考设计明确要求，或 SI/EMC 实测证明需要时才使用。**

#### 3.6.2、共模扼流圈同样不是免费午餐

它可能改善特定频段的共模辐射，也可能引入：

- 差模插损；
- 寄生电容；
- group delay；
- pair imbalance。

如果为了 EMC 预留 footprint，应评估空焊盘自身 stub 和阻抗影响，并尽量使用经过 MIPI 高速接口验证的器件。

---

### 3.7、TE、Reset、Backlight、Panel ID 等辅助信号

#### TE

TE（Tearing Effect）主要用于让 Host 与 Panel 刷新时机协调，尤其常见于 Command Mode。

两种常见路径：

1. Panel TE → SoC GPIO，中断后由软件调度；
2. Panel TE → 显示/DSI 控制器专用输入，由硬件参与同步。

前者灵活，但会叠加中断、调度和软件路径抖动；后者时延更确定，但依赖 SoC 硬件能力和 pinmux。

Video Mode 下不一定需要 TE，是否使用取决于 Panel、控制器和刷新策略。

#### Panel ID

多供应商场景可采用：

- 独立 ID GPIO；
- 通过 DCS/厂商命令读 Panel ID；
- Bootloader/EEPROM/生产烧录标识；
- BOM/板级 SKU 固定绑定。

每种方案都要考虑“**屏未正常初始化时还能不能识别**”。如果识别本身依赖一套未知初始化表，就形成了经典的先有鸡还是先有屏驱动问题。

---

### 3.8、完整硬件评审表

| 条目 | 检查方法 | 通过判据 | 常见失效 |
| --- | --- | --- | --- |
| Panel 电源电压 | 对照 Panel Spec 与 PMIC | 全部 rail 在允许范围 | 不亮、闪烁、寿命风险 |
| 上下电顺序 | 原理图 + 示波器 | 满足 Panel 时序 | 偶发黑屏、冷启动失败 |
| Reset 默认状态 | GPIO/上拉下拉检查 | 上电无浮空、满足时序 | 首次启动概率失败 |
| Backlight 时序 | 示波器/软件日志 | 图像稳定后开、关机先灭 | 白闪、残影 |
| Lane mapping | 原理图/FPC pinout | Host/Panel 一致 | 完全不亮、SoT 错误 |
| Lane polarity | 原理图 + Host 能力 | 若交换必须由硬件/IP支持 | 无法锁定 |
| 差分/单端阻抗 | Stackup + PCB 约束 | 满足 SoC/PHY 指南 | 高频花屏、温漂敏感 |
| P/N skew | PCB constraint report | 满足设计指南 | 眼图变差、误码 |
| Clock/Data skew | PCB + package 约束 | 满足目标速率要求 | 高速率失败 |
| 参考平面 | Layout review | 连续、不跨 split | EMI/反射/随机错误 |
| Via 数与对称性 | Layout review | 满足设计指南 | skew、损耗增加 |
| 分支/stub | Layout review | 无不必要分支 | 反射、速率上不去 |
| FPC 阻抗 | 厂家规格/仿真 | 满足通道要求 | 批次差异大 |
| 连接器回流 | pinout/Layout | GND 配置合理 | EMI、串扰 |
| ESD 器件 | Datasheet + SI | 适配目标速率并通过验证 | 低温/高速花屏 |
| 串阻/CMC | 原理图评审 | 有明确依据，否则 DNP/删除 | 眼图恶化 |
| TE 连接 | 原理图 + pinmux | 符合软件同步方案 | 撕裂/抖动 |
| ID 识别 | 原理图 + 软件流程 | 冷启动可确定识别 | 多屏误识别 |

---

## 第四章、PHY 参数与链路裕量：能跑和跑得稳不是一回事

> **本章解决的工程决策**：目标 lane rate 是否安全；PHY 时序参数由谁生成、能否调整；当前链路离失效边界还有多少距离。

### 4.1、先建立 PHY 参数的四类来源

看到一个 PHY 参数时，先分类，而不是先猜数值。

| 来源 | 示例 | 工程含义 |
| --- | --- | --- |
| 规范约束 | LP/HS 状态、电平、时序窗口 | 不能任意违反 |
| SoC PHY/IP 自动生成 | 部分 HS timing、termination 控制 | 软件可能只给 lane rate，硬件内部换算 |
| SoC 可编程寄存器 | HS-PREPARE、settle、PLL 等 | 需要按 TRM/驱动换算 |
| Panel/DDIC 特殊要求 | 接收范围、ULPS、初始化延时 | 必须纳入最终配置 |

因此看到“参考代码里写 `0x14`”时，第一反应应该是：

```text
0x14 是什么单位？
它对应哪一代 PHY？
由 byte clock 还是 ref clock 换算？
为什么对这个 Panel 合法？
```

而不是把它复制到另一个项目，等待硬件用花屏表达意见。

---

### 4.2、LP 与 HS 是同一组线上的两套工作方式

传统 D-PHY Data Lane 同时承担：

- LP：单端、低速、状态控制；
- HS：低摆幅差分、高速数据。

这意味着：

1. 线路上的器件必须同时兼容 LP 与 HS；
2. 普通“高速差分接口经验”不能完全照搬；
3. LP 段的状态切换通常比 HS 眼图更容易观测，但也不能理解成任何普通探头都不会影响链路。

调试 LP 状态时应使用：

- 足够高输入阻抗；
- 尽量低探头电容；
- 短接地路径；
- 明确参考 SoC/Panel 电气电平。

HS 信号则优先使用合适的高速差分探头和带宽，而不是拿探头一夹，看到“有波形”就宣布信号完整性通过。

---

### 4.3、从 Stop State 进入 HS：失败通常发生在哪里

对 forwarded-clock D-PHY，可以把一次 HS 传输抽象成：

```text
LP Stop State
   ↓
请求进入 HS
   ↓
HS Prepare
   ↓
HS Zero
   ↓
同步 / SoT
   ↓
HS Payload
   ↓
HS Trail
   ↓
返回 LP
```

工程上重点不是死背状态编码，而是把错误映射到阶段：

| 现象 | 优先怀疑 |
| --- | --- |
| 一直停在 LP、没有 HS | Host 未启动、时钟/电源/状态机没进入 |
| 有 HS 边沿但接收端不认 | HS timing、lane mapping、速率、终端、SI |
| SoT 错误大量出现 | 同步、skew、眼图、速率/PHY 时序 |
| 低速可用，高速开始错 | 通道损耗、skew、PHY 参数、EMI |
| 常温正常，高低温错误 | 电气裕量过小、PLL/电源/Panel 接收窗口 |

排查错误寄存器时，要注意不同 DSI Host IP 对错误位命名并不统一，不能把一颗 SoC 的位定义直接套到另一颗上。

---

### 4.4、关键 PHY 时序参数怎么理解

下面不写规范固定上下限，避免读者把一个版本的数字硬套到另一个 PHY 版本。

| 参数 | 工程含义 | 一般由谁产生 | 失配可能表现 |
| --- | --- | --- | --- |
| TLPX | LP 状态保持/切换的基础时间 | PHY/IP | LP/HS 切换异常 |
| THS-PREPARE | 进入 HS 前准备窗口 | PHY/IP 或寄存器 | SoT、无法进入 HS |
| THS-ZERO | HS 驱动稳定到同步前的时间 | PHY/IP 或寄存器 | 接收端锁定失败 |
| THS-TRAIL | HS 数据结束后的尾部时间 | PHY/IP | 尾包错误、返回 LP 异常 |
| THS-EXIT | HS 结束后过渡回 LP（Stop State）所需的窗口 | PHY/IP | 连续传输边界异常 |
| TCLK-PREPARE | Clock Lane 进入 HS 准备 | PHY/IP | 时钟锁定失败 |
| TCLK-ZERO | HS Clock 稳定窗口 | PHY/IP | Data 接收窗口异常 |
| TCLK-PRE | 数据发送前 Clock 已稳定的时间 | PHY/IP | 起始接收不稳 |
| TCLK-POST | 数据结束后继续保持 Clock 的时间 | PHY/IP | 尾部接收异常 |
| TWAKEUP | 从 ULPS 等状态退出的唤醒等待 | Host/Panel | 唤醒后首帧失败 |

#### 参数来源优先级

```text
1. 当前 SoC/PHY 官方 BSP / Reference Driver
2. 当前 SoC TRM / PHY Programming Guide
3. Panel/DDIC 明确附加要求
4. MIPI 对应版本规范
5. 实测微调
```

“实测调好”只能排在最后。因为如果完全不知道寄存器含义，只靠扫参数扫出一个能亮的值，项目只是把 bug 变成了玄学配置。

---

### 4.5、终端、共模与摆幅

D-PHY HS 接收端通常由 PHY 内部按状态控制终端，外部 PCB **通常不再并一个 100 Ω 电阻来模仿普通 LVDS 接收器**。

排查 HS 电气问题时重点观察：

- 差分摆幅是否落在 Tx/Rx 规格范围；
- common-mode 是否异常；
- P/N 是否对称；
- 进入 HS 时接收终端是否按预期工作；
- ESD/CMC/连接器是否造成明显反射与衰减。

如果示波器看起来幅度“不够漂亮”，先确认探测方法和测量点，再决定是不是 PHY 真有问题。高速接口很擅长把测量系统本身也纳入故障链路。

---

### 4.6、Escape Mode、BTA 与 ULPS

#### Escape Mode

Escape/LP 通常承载低速控制类操作，具体用途随 DSI 控制器实现和协议操作而定。

#### BTA（Bus Turn-Around）

当 Host 需要让 Peripheral 在链路上返回数据时，必须完成总线方向切换。问题通常集中在：

- Host 没有正确发起 BTA；
- turnaround timing 不满足；
- Panel 没有响应或响应过慢；
- Host 提前重新驱动造成 contention；
- 反向 LP 信号被 ESD/外围器件影响；
- 控制器只支持有限的 read/BTA 方式。

所以“写命令正常、读 ID 异常”并不能说明 DSI 基本没问题，它可能恰好把问题缩小到了 LP 反向路径。

#### ULPS

ULPS 的价值是降低静态功耗，但代价是：

- 进入/退出有明确时序；
- Panel 和 Host 都要支持；
- 唤醒后需要重新建立可用链路；
- 某些平台还会联动 PHY/PLL/clock gating。

量产时必须回归：

```text
进入 ULPS → 保持 → 退出 → 首帧 → 连续多次循环
```

不能只测试“第一次唤醒成功”。

---

### 4.7、高速率下必须额外关注什么

#### 4.7.1、Skew Calibration

在传统 forwarded-clock D-PHY 的常见规范版本中，当 lane rate 超过约 1.5 Gbit/s 时，初始 skew calibration 会成为必须关注的机制；更新 PHY 版本在更高速率下还会叠加其他校准、均衡或 preamble 机制。

这里不建议把阈值背成永恒常数。项目应确认：

- 当前 PHY 版本；
- Host TX 是否会发 calibration sequence；
- Panel RX 是否支持；
- 控制器是否自动完成；
- 是否存在校准完成/失败状态位。

#### 4.7.2、Jitter 与 Eye Margin

速率提高后，UI 变短，同样的绝对抖动和 skew 会占据更大比例的采样窗口。

因此“PCB 长度差没变”不代表 500 Mbps 和 2.5 Gbps 风险一样。

#### 4.7.3、Spread Spectrum Clocking

SSC 可以帮助分散某些频段的峰值 EMI，但必须同时确认：

- 当前 D-PHY/IP 是否支持；
- Panel 接收端是否允许；
- 调制深度/频率是否在允许范围；
- 是否压缩了本来就不多的时序裕量。

SSC 是 EMC 手段，不是看到某个认证点超标后随便勾一个 checkbox。

---

### 4.8、怎样评价“链路裕量”

不要只写一句“margin 足够”。建议至少拆成五维：

| 维度 | 评价依据 | 高风险表现 |
| --- | --- | --- |
| 带宽裕量 | 目标 lane rate / 双侧额定上限 | 已接近器件上限 |
| SI 裕量 | PCB/FPC/连接器/ESD 是否满足约束 | 设计边界项很多 |
| PHY 时序裕量 | 参数来源是否明确、是否位于有效窗口 | 只能靠某个窄参数点工作 |
| 环境裕量 | 高低温、电压 corner 结果 | 温度变化后错误暴增 |
| 供应商裕量 | 两家 Panel 的共同工作窗口 | 每家都要不同极端配置 |

#### 4.8.1、推荐的等级定义

**High Margin**：

- 配置远离器件额定上限；
- HW 约束全部有依据；
- 两家 Panel 有共同工作窗口；
- 温度、电压和批次扫描无明显错误增长。

**Medium Margin**：

- 部分参数靠近边界；
- 有少量 conditional item；
- 需要通过额外回归和监控才能接受。

**Low Margin**：

- 必须使用极端 PHY 参数才稳定；
- 只在特定 Panel 批次或常温工作；
- lane rate 接近一侧硬上限；
- 任意小改动都会改变结果。

Low Margin 不应靠“已经连续跑了半小时”转化为 High Margin。时间不能炼金。

本章对应 1.2 节承诺的"PHY 参数与裕量表"，由 4.4 的参数表（取值来源与失配表现）与本节的五维裕量评价共同构成，评审时应两张表一并提交，而不是只挑一张。

---

## 第五章、软件参数归属与多 Panel 架构

> **本章解决的工程决策**：参数应该写在哪里，怎样避免换 Panel 时全工程搜索 magic number，以及任何参数变化后必须回归哪些测试。

### 5.1、先把参数分成四类

#### A. 面板固有参数

例如：

- native resolution；
- display timing / mode；
- reset timing；
- DCS / vendor init sequence；
- sleep out / display on 等等待；
- Panel ID / revision；
- orientation、物理尺寸等。

这些参数原则上跟着 Panel 型号走。

#### B. DSI 链路参数

例如：

- Data Lane 数；
- pixel format；
- Video/Command Mode；
- burst/non-burst；
- mode flags；
- lane rate；
- DSC 配置；
- ULPS/continuous clock 策略。

它们通常由 Host 与 Panel 能力交集决定。

#### C. 平台资源参数

例如：

- regulator；
- reset GPIO；
- enable GPIO；
- backlight；
- pinctrl；
- DSI host/bridge 拓扑；
- clocks / resets。

这类参数更接近板级硬件描述。

#### D. 工程调试参数

例如：

- 强制某 lane rate；
- 打印错误计数；
- 强制纯色；
- 跳过 ULPS；
- 显示当前 panel ID / timing / PHY 配置。

这些不应该污染正常产品配置路径。

---

### 5.2、硬编码、配置表、设备树分别适合什么

| 承载方式 | 适合 | 不适合 |
| --- | --- | --- |
| C 代码常量/Panel descriptor | Panel 固有初始化、驱动逻辑 | 板级 GPIO/电源拓扑 |
| 设备树 | 板级硬件连接、资源、拓扑、compatible | 巨大的私有 init blob，除非 binding 明确规定 |
| Firmware/NVM | 需要独立版本管理、量产烧录的可变数据 | 启动早期必须立即可用但读取链路不可靠的关键配置 |
| Debugfs/sysfs/模块参数等 | 调试和观测 | 长期产品真值来源 |

一个简单判断标准：

> **换一块同板级接口的 Panel，理想情况下应该主要新增/替换一个 Panel 描述，而不是去 Host、时钟、GPIO、业务代码里改十几个文件。**

---

### 5.3、变更与回归矩阵

| 变更 | 影响面 | 最小回归集 |
| --- | --- | --- |
| Lane 数 | 带宽、pin mapping、PHY | bring-up、速率、高低温、EMC |
| lane rate | PLL/PHY/SI/EMI | 误码、温度、EMC、长稳 |
| pixel format/bpp | 带宽、颜色 | 画面、带宽、色彩、EMC |
| porch/timing | pixel clock、blanking、Panel 接收 | 全分辨率画面、帧率、长期稳定 |
| init table | Panel 内部状态 | 冷/热启动、休眠唤醒、亮度、画质 |
| PHY timing | 电气边界 | 高低温、电压 corner、长稳 |
| 新增供应商 | 几乎全部 | 至少完整供应商准入集 |
| 开/关 DSC | 协议、画质、带宽 | PPS、画质、恢复、温度、EMC |
| TE 路径 | 同步与调度 | tearing、帧延迟、压力测试 |

这张矩阵的意义是让测试需求在“参数发生变化的那一刻”就生成，而不是发布前突然有人问“换了屏是不是要重新测”。

---

### 5.4、Linux DRM/KMS 侧应该怎样理解对象关系

可以用下面的抽象链路理解：

```text
Framebuffer
   ↓
Plane
   ↓
CRTC
   ↓
Encoder
   ↓
Bridge(s)
   ↓
Connector / Panel
```

实际 SoC 驱动未必把每一级都以肉眼可见的独立硬件块呈现，但这个模型有助于区分职责。

对于 MIPI DSI，Linux 还有两类关键对象：

```text
mipi_dsi_host    ← SoC DSI Host Controller
      │
      └── mipi_dsi_device ← Panel / Bridge 这个 DSI peripheral
```

当前内核的 `mipi_dsi_device` 会描述：

- virtual channel；
- lanes；
- pixel format；
- mode flags；
- HS/LP rate 能力；
- 部分情况下还包含 DSC 相关配置。

Panel driver 通常先设置这些能力，再 attach 到 Host。具体调用顺序仍以当前内核 API 和平台驱动为准。

---

### 5.5、Panel 驱动生命周期不要混在一起

推荐把语义保持清楚：

```text
prepare()
    上电
    reset
    等待
    发送初始化命令
    让 Panel 进入“可显示但还未真正出图”的状态

get_modes()
    提供支持的 display mode

enable()
    Display On / 配合 backlight 打开

disable()
    关闭显示 / 先灭 backlight

unprepare()
    Sleep In
    reset（如需要）
    断电
```

真正实现时不同 Panel 的命令可能位于不同回调，但必须保证两个原则：

1. **生命周期语义可读**；
2. **任何中途失败都能按相反顺序 rollback。**

伪代码示例：

```c
static int panel_prepare(struct drm_panel *panel)
{
    int ret;

    ret = regulator_enable(...);
    if (ret)
        return ret;

    reset_assert(...);
    delay_from_panel_spec();
    reset_deassert(...);
    delay_from_panel_spec();

    ret = panel_send_init_sequence(...);
    if (ret)
        goto err_poweroff;

    return 0;

err_poweroff:
    reset_assert(...);
    regulator_disable(...);
    return ret;
}
```

注意：这里的延时名称是语义占位，不应该把某款 Panel 的 10 ms、120 ms 之类数字伪装成通用值。

---

### 5.6、设备树应该描述“板上是什么”，不是“调试时我想怎么试”

一个直接挂在 DSI Host 下的 Panel，常见概念结构类似：

```dts
&dsi {
    status = "okay";

    panel@0 {
        compatible = "vendor,panel-model";
        reg = <0>;                  /* DSI virtual channel */
        power-supply = <&vcc_lcd>;
        reset-gpios = <&gpioX Y GPIO_ACTIVE_LOW>;
        backlight = <&backlight>;
    };
};
```

需要强调三点：

1. `compatible` 应描述真实硬件型号/兼容关系，不应为了偷懒把所有供应商都写成一个虚构 generic panel。
2. `reg` 在 DSI Panel binding 中通常表示 virtual channel，不是 I²C 地址。
3. Panel 与 display 的关联既可能通过“Panel 是 DSI Host 的 child node”表达，也可能使用 OF graph `port/endpoint`，具体取决于 binding 和平台拓扑。

如果中间有 bridge：

```text
CRTC/Encoder → DSI Host → DSI-to-eDP/LVDS Bridge → Panel
```

此时 OF graph 会更重要，调试也多出：

- DSI 侧；
- Bridge 内部寄存器；
- Bridge 输出侧；
- 下游 Panel；

四层状态。于是一个黑屏可以拥有更丰富的人生。

---

### 5.7、RTOS / 裸机路径

没有 DRM 时，仍建议保留明确分层：

```text
board_power_init()
        ↓
phy_init()
        ↓
dsi_host_init()
        ↓
panel_detect()
        ↓
panel_prepare()
        ↓
display_controller_init()
        ↓
panel_enable()
        ↓
first_frame
```

上面的 `panel_detect()` 顺序只对 ID GPIO、EEPROM/NVM/SKU 等无需 Panel 通电即可完成的识别方式成立。若识别方式是 DSI Read ID（见 5.8），则必须先完成上电与 Reset 释放（可从 `panel_prepare()` 中拆出最小的“上电 + 复位”子步骤），再读取 Panel ID，否则读不到任何有效响应。

常见遗漏：

- PLL 已开但 PHY 未退出 reset；
- DSI Host 已配置但 Panel 还没完成 reset；
- video timing 和 Panel timing 不一致；
- lane rate 计算使用 active timing 而不是 total timing；
- 第一帧送出时背光已提前开启；
- 错误路径没有关闭电源，导致第二次初始化状态不同。

最好像 Linux 一样保留明确的 prepare/enable/disable/unprepare 语义，即使最终只是几个 C 函数。

---

### 5.8、多 Panel 兼容架构

推荐数据结构：

```c
struct panel_desc {
    const char *name;
    uint32_t panel_id;

    struct display_mode mode;

    uint8_t lanes;
    enum pixel_format format;
    uint32_t dsi_flags;

    const struct panel_cmd *init_seq;
    size_t init_seq_num;

    const struct phy_profile *phy;
    const struct regression_profile *regression;
};
```

流程：

```text
board identification
      ↓
panel identification
      ↓
lookup panel_desc
      ↓
apply link config
      ↓
run panel lifecycle
```

当 panel identification 采用 DSI Read ID 方式时，此步骤必须晚于最小化的上电/Reset 子步骤（见 5.7），不能严格早于 lifecycle 执行；ID GPIO / EEPROM / SKU 等方式则不受此限制。多供应商场景下，识别尚未完成、`panel_desc` 尚未查到，这个最小上电/Reset 子步骤应采用所有候选 Panel 中最保守（最长）的电源稳定时间与 Reset 延时的并集，而不是任一具体 `panel_desc` 的数值；识别成功后再按查到的 `panel_desc` 补齐/校正剩余的 prepare 时序。

#### 识别策略比较

| 方式 | 优点 | 风险 |
| --- | --- | --- |
| ID GPIO | 启动早、简单 | 占 pin，BOM 要严格管理 |
| DSI Read ID | 不额外占 pin | 依赖 BTA/LP read 和 Panel 可响应状态 |
| EEPROM/NVM/SKU | 与生产管理结合好 | 生产写错会造成逻辑误配 |
| Bootloader 改 DT/Overlay | Linux 边界清晰 | bootloader 复杂度增加 |

Linux 主线语义里，设备树应尽量描述实际硬件。如果同一 PCB 可能装不同 Panel，更干净的做法往往是让 Bootloader/生产 SKU 选择正确 DT/overlay，或者使用有明确 binding 支持的检测方式；不要默认“一个 panel driver 运行时猜所有屏”就是最佳架构。

---

### 5.9、量产固件必须保留哪些观测能力

建议保留只读或受控调试接口：

- 当前识别到的 Panel 型号/ID/Revision；
- 当前 display mode；
- lane 数、pixel format、mode flags；
- 实际 lane/byte clock；
- PHY timing 计算结果；
- DSI Host 错误计数；
- 最近一次初始化失败阶段；
- 休眠/唤醒次数与失败次数；
- 强制纯色/测试图；
- 在工程版本中允许切换安全范围内的速率档。

量产版不一定要暴露写寄存器的万能后门，但至少要能回答“现场这台机器到底跑的是什么配置”。否则日志只有一句 `panel init failed`，其信息密度与叹气差不多。

---

## 第六章、附录：速查、迁移地图与规范索引

> 本章不再引入新的主线知识，只把前五章压缩成项目现场可以直接查、直接归档的形式。

### 6.1、方案决策速查

```text
是否必须用 DSI？
  └─ 先比较针脚、带宽、SoC/Panel 生态，不要默认。

D-PHY 还是 C-PHY？
  └─ 看 Host 与 Panel 双侧真实能力，不看“谁更新”。

几条 Lane？
  └─ timing + bpp + FPS + 协议模式算带宽，再取双侧/硬件交集。

要不要 DSC？
  └─ 未压缩方案在合理 Lane 数和额定速率仍不够时再考虑。

速率配多少？
  └─ 不是“刚好够”，而是额定范围内保留可验证裕量。

样机亮了是否完成？
  └─ 没有。还差硬件评审、PHY 裕量核实，以及多 Panel 参数的可维护性回归。
```

---

### 6.2、PHY 规范索引与版本意识

截至 2026-09，MIPI Alliance 官网列出的主要当前版本包括：

- MIPI DSI v1.3.2；
- MIPI DSI-2 v2.2；
- MIPI D-PHY v3.6；
- MIPI C-PHY v3.1；
- MIPI DCS v2.1。

这些是**规范当前版本**，不代表你的 SoC 和 Panel 实际实现了这些版本。

项目必须优先确认：

```text
SoC TRM / datasheet 声明的 DSI 版本
SoC D-PHY/C-PHY 版本
Panel/DDIC 声明的接收能力
BSP driver 实际支持能力
```

正文没有展开的规范内容包括：

- 完整 D-PHY 电气上下限；
- 每一个 timing 的 min/max 公式；
- 完整状态机；
- DSI 所有 packet type；
- DCS 全命令集；
- DSC/PPS 完整字段。

这些内容在真正需要配置或做一致性测试时，应查对应规范与器件手册，而不是从本文复制一个可能属于不同版本的常数。

---

### 6.3、CSI-2 知识迁移地图

从 DSI 转去学 CSI-2，可以直接复用：

- D-PHY/C-PHY 基本电气概念；
- Lane、HS/LP、skew、termination；
- packet header / ECC / CRC 的思维方式；
- 带宽与 lane rate 预算方法；
- PCB/FPC 高速链路评审框架；
- SI/EMI 与裕量验证方法。

需要重新学习：

- CSI-2 的 camera source → receiver 数据方向；
- image data type；
- Frame Start/End、Line Start/End 等包语义；
- RAW10/RAW12/RAW14 等 packing；
- Embedded Data；
- virtual channel 的摄像头用法；
- sensor timing 与曝光/帧率关系；
- Linux V4L2、media controller、subdev graph。

尤其不要把 DSI 的 BTA/Panel Command Mode 逻辑硬搬到 CSI-2。两者共用 PHY，不等于上层协议是一回事。

---

### 6.4、易错点对照表

| 错误理解 | 更准确的说法 |
| --- | --- |
| C-PHY 一定比 D-PHY 好 | 只在 Host、Panel、PCB、工具链都支持时才有意义 |
| D-PHY 一定有独立 Clock Lane | 传统模式如此；新版本已有可选 embedded-clock |
| 只有 DSI-2 才支持 DSC | 传统 DSI 规范本身也纳入 DSC |
| Lane 越少越省成本 | Lane 少会提高单 Lane rate，可能增加 SI/EMI 风险 |
| 计算出来 400 Mbps 就配 400 Mbps | active payload 只是下限，还要考虑 total timing 和协议/控制器约束 |
| 100 Ω 是全世界所有 MIPI 板子的唯一答案 | 100 Ω diff 很常见，但项目必须以 SoC/PHY design guide 为准 |
| MIPI 高速线加串阻总能改善振铃 | 未验证串阻可能同时破坏 HS/LP 行为 |
| TVS 越强越安全 | 过大的寄生参数会先把高速链路弄死 |
| 屏亮了说明 SI 没问题 | 只说明当前样机当前环境暂时能工作 |
| 同规格 Panel 可以直接替换 | DDIC、init、timing、FPC、电气窗口都可能不同 |
| PHY timing 直接照参考代码 | 先确认 PHY 版本、单位、lane rate 和寄存器换算 |
| 高低温只看画面 | 还应看错误计数、首帧、BTA、ULPS、唤醒等 |
| 老化就是让屏一直亮 | 要根据真实用户行为设计常亮/休眠/上下电循环 |

---




