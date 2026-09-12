# ARM Cortex-M：从内核机制到 RTOS 与故障定位

> 目标：建立 Cortex-M 的完整心智模型，能把寄存器、启动流程、异常/中断、栈、RTOS 上下文切换和 HardFault 串成一条链路。
>
> 范围：本文讨论 Cortex-M **内核通用机制**。GPIO、UART、SPI、DMA 控制器以及具体 Flash/SRAM 地址由 MCU 厂商决定，最终以芯片手册、启动文件和链接脚本为准。

---

## 1. 先建立全貌：Cortex-M 是什么

**Cortex-M 是 ARM 面向 MCU 和实时嵌入式场景设计的 CPU 内核系列。** MCU 厂商将内核、片上存储器、总线和外设集成，才形成 STM32、NXP、Nordic 等具体芯片。

```text
ARM 架构
  └── Cortex-M 内核
        ├── CPU 与核心寄存器
        ├── 异常机制、NVIC、SysTick
        ├── MPU、调试组件
        └── （部分内核）FPU、Cache、TrustZone
                 │
                 ▼
MCU 厂商集成：Flash / SRAM / GPIO / UART / SPI / 定时器 / DMA ...
```

因此：**Cortex-M ≠ STM32。** NVIC、异常机制、核心寄存器属于内核；UART 寄存器、时钟树和 Flash 地址属于具体芯片。

| 常见内核 | 核心印象 | 常见场景 |
| --- | --- | --- |
| Cortex-M0/M0+ | 精简、低功耗 | 小型 MCU |
| Cortex-M3 | 经典 MCU 内核 | STM32F1 等 |
| Cortex-M4 | M3 + DSP，FPU 可选 | 控制、音频、STM32F4 等 |
| Cortex-M7 | 性能更高，可带 I/D Cache、FPU | 高性能控制、STM32H7 等 |
| Cortex-M23/M33 | ARMv8-M，可支持 TrustZone | 安全 MCU |

不同内核支持的 Fault、优先级位数、FPU/Cache/MPU 并不完全相同；通用原理之外仍需查目标内核手册。

## 2. CPU 如何执行代码：寄存器、调用与栈

### 2.1 常用核心寄存器

| 寄存器 | 名称 | 作用 |
| --- | --- | --- |
| `R0`–`R12` | 通用寄存器 | 参数、临时值和计算结果 |
| `R13` / `SP` | Stack Pointer | 指向当前栈顶 |
| `R14` / `LR` | Link Register | 普通调用时保存返回地址；异常时承载 `EXC_RETURN` |
| `R15` / `PC` | Program Counter | 指向下一步执行的位置 |
| `xPSR` | 程序状态寄存器 | 条件标志、异常号和 Thumb 状态等 |

程序本质上不断执行“取指、执行、更新 `PC`”：

```text
PC 指向指令 → 取指并执行 → PC 更新 → 下一条指令
```

`PC` 是故障定位的核心：异常栈帧保存的 `PC` 通常能定位发生异常的位置。普通函数调用常使用类似 `BL foo` 的指令跳到函数，并将返回地址写入 `LR`；函数再用 `BX LR` 一类指令返回。

### 2.2 SP 与栈

函数局部变量、被保存的寄存器和返回地址通常位于栈上；`SP` 始终指向栈顶。多数 Cortex-M 工程的栈向低地址增长：

```text
地址高
+---------------------------+
| 更早的调用帧 / 局部变量    |
+---------------------------+
| 当前函数保存的 LR、寄存器  |
+---------------------------+
| 当前函数局部变量           |
SP -> +---------------------------+
地址低
```

局部数组过大、调用层次过深、中断嵌套、任务栈过小都可能溢出。它经常表现为随机跑飞、返回地址损坏或稍后发生的 HardFault，而不一定在越界语句处报错。

### 2.3 MSP 与 PSP：两套栈指针

| 栈指针 | 名称 | 典型用途 |
| --- | --- | --- |
| `MSP` | Main Stack Pointer | 复位后默认使用；Handler mode 必须使用 |
| `PSP` | Process Stack Pointer | Thread mode 可选使用；RTOS 常为每个任务配置 |

```text
异常 / 中断（Handler mode） → MSP
裸机 main()（Thread mode）  → 通常 MSP
RTOS 任务（Thread mode）    → 通常 PSP，每个任务各有任务栈
```

可先记为：**MSP 常服务内核和异常，PSP 常服务 RTOS 任务。** 裸机项目不一定会使用 PSP，取决于系统设计。

## 3. 从复位到 `main()`：向量表、启动文件与内存

### 3.1 向量表

程序复位后，内核靠向量表取得初始栈和异常处理入口：

```text
第 0 项  Initial MSP
第 1 项  Reset_Handler
第 2 项  NMI_Handler
第 3 项  HardFault_Handler
...      SysTick、外设 IRQ Handler
```

第 0 项不是函数地址，而是 `MSP` 初值；第 1 项才是 `Reset_Handler`。带 Bootloader 的应用通常不在 Flash 起始地址，需要按芯片规则重定位向量表（常见为设置 `SCB->VTOR`）。

### 3.2 启动流程

```text
上电 / Reset
    ↓
读取向量表：Initial MSP、Reset_Handler
    ↓
SystemInit()：时钟和芯片早期初始化
    ↓
复制 .data 初值：Flash → RAM；清零 .bss
    ↓
C/C++ 运行库初始化
    ↓
main()
```

```c
int g_ready = 1;    /* .data：初值在 Flash，运行实体在 RAM */
int g_count;        /* .bss：启动时清零，运行于 RAM */
```

### 3.3 Flash、RAM 与常见段

```text
Flash： [ 向量表 ][ .text ][ .rodata ][ .data 初值 ]
RAM：   [ .data ][ .bss ][ heap  →      ←  stack ]
```

| 内容 | 常见位置 | 说明 |
| --- | --- | --- |
| 函数机器码 | `.text` / Flash | 有些场景会搬到 RAM 执行 |
| 字符串、查找表、只读常量 | `.rodata` / Flash | `const` 不绝对等于 Flash |
| 已初始化全局/静态变量 | `.data` / RAM | 初值也占用 Flash |
| 未初始化或零初始化全局/静态变量 | `.bss` / RAM | 镜像通常只记录长度 |
| 局部变量、调用信息 | stack | 优化后也可能只在寄存器 |
| `malloc()` 对象 | heap | 取决于 C 库与链接脚本 |

## 4. 执行状态、异常与 NVIC

### 4.1 Thread mode 和 Handler mode

```text
Thread mode：main()、裸机主循环、RTOS 任务
Handler mode：IRQ、SysTick、PendSV、HardFault 等异常处理函数
```

```text
Thread mode 正在执行
    ↓ 接受异常
硬件保存异常现场，进入 Handler mode
    ↓
执行 ISR
    ↓ 异常返回
恢复现场，回到原 Thread mode 位置
```

“被打断”通常发生在机器指令边界，不表示一条指令只执行了一半。工程上应假定中断可能发生在任意两条普通指令之间。

### 4.2 IRQ 是 Exception 的一种

Cortex-M 将 Reset、HardFault、SVCall、PendSV、SysTick 与外设中断统一纳入异常（Exception）系统。`NVIC`（Nested Vectored Interrupt Controller）负责外部中断的使能、挂起、优先级仲裁和嵌套。

```text
UART 置接收标志并提出 IRQ
    ↓
NVIC 判断：是否使能、是否被屏蔽、优先级能否抢占
    ↓
CPU 接受异常，压入异常现场
    ↓
根据向量表跳转 USARTx_IRQHandler
    ↓
ISR 读取数据/清中断源，异常返回
```

外设负责发现事件；NVIC 负责记录和仲裁；CPU 负责保存/恢复现场并执行 Handler。ISR 必须按外设手册读取数据或清标志，否则中断可能立刻再次触发。

### 4.3 优先级的易错点

1. **数值越小，逻辑优先级越高。** 例如 `1` 高于 `5`。
2. 芯片实现的优先级位数有限，NVIC 寄存器通常只有高位有效；CMSIS/HAL 的优先级分组也会影响最终抢占关系。不要只看一个裸数值下结论。

## 5. 异常现场：为什么能够原位恢复

异常入口时，硬件自动压入基本异常栈帧：

```text
高地址
+------------------+
| xPSR             |
+------------------+
| PC               | ← 定位故障的重要地址
+------------------+
| LR               |
+------------------+
| R12              |
+------------------+
| R3 / R2 / R1 / R0|
+------------------+
低地址（SP 指向此处，示意）
```

也就是 `R0`–`R3`、`R12`、`LR`、`PC`、`xPSR`。Handler 若使用 `R4`–`R11`，编译器会按 ABI 规则另行保存；启用 FPU 且使用浮点上下文时，异常帧也可能扩展。

异常期间 `LR` 是特殊的 `EXC_RETURN`，编码异常返回应恢复的模式、MSP/PSP 选择及浮点帧信息。因此 HardFault 处理首先判断它，才能知道异常帧在 MSP 还是 PSP。

## 6. 中断屏蔽与 RTOS 常用异常

### 6.1 `PRIMASK`、`BASEPRI`、`FAULTMASK`

| 寄存器 | 核心用途 | 工程理解 |
| --- | --- | --- |
| `PRIMASK` | 屏蔽可配置优先级的异常 | 常见“全局关中断”；NMI、HardFault 不受影响 |
| `BASEPRI` | 屏蔽优先级不高于阈值的可配置异常 | 保留高优先级实时 IRQ，RTOS 常用 |
| `FAULTMASK` | 屏蔽除 NMI 外的异常 | 很少需要，误用会掩盖故障 |

`__disable_irq()` / `__enable_irq()` 通常操作 `PRIMASK`。临界区应尽量短，长时间关中断会带来丢数据、控制抖动和更差的中断延迟。

### 6.2 SysTick、SVC、PendSV

| 异常 | 典型职责 |
| --- | --- |
| SysTick | 周期时基、tick、超时、延时和时间片 |
| SVC / SVCall | 用 `SVC` 指令请求特权服务；常用于系统调用或启动调度器 |
| PendSV | 可软件挂起，通常设为很低优先级；适合延后执行任务切换 |

```text
SysTick 到期 → 内核发现需要切换任务 → 挂起 PendSV
    ↓
更紧急的中断处理完毕
    ↓
PendSV 执行上下文切换
```

## 7. RTOS 如何切换任务

以“任务使用 PSP、异常使用 MSP”的常见设计为例：

```text
Task A（PSP_A）运行
    ↓ PendSV 异常进入
硬件自动保存：R0–R3、R12、LR、PC、xPSR 到 Task A 栈
RTOS 保存：R4–R11（需要时还有浮点寄存器）
    ↓
将 PSP_A 写入 TCB_A，取出 TCB_B 中的 PSP_B
    ↓
恢复 Task B 的 R4–R11，异常返回
    ↓
硬件自动恢复剩余现场，Task B 继续
```

**硬件负责基本异常帧，RTOS 负责其余上下文和调度数据。** 这就是 FreeRTOS PendSV 汇编的主线。

能调用 RTOS `FromISR` API 的中断还必须满足该 RTOS 的优先级约束；高优先级、不可被内核屏蔽的 IRQ 通常只能做与内核隔离的极短处理。具体阈值应查工程的 `FreeRTOSConfig.h` 或 RTOS 文档。

## 8. Fault 与 HardFault：从崩溃到源码定位

### 8.1 常见 Fault

| Fault | 常见原因 |
| --- | --- |
| UsageFault | 未定义指令、除零、未对齐访问、非法状态切换等 |
| BusFault | 无效地址或总线访问错误、取指/数据访问失败 |
| MemManage Fault | MPU 权限或内存属性违规 |
| HardFault | 严重错误，或可配置 Fault 未启用/进一步升级 |

部分内核不具备上述可配置 Fault，或其被禁用时会升级到 HardFault；必须结合目标 Cortex-M 型号判断。

### 8.2 可靠的排查流程

```text
进入 HardFault_Handler
    ↓
根据 EXC_RETURN 判断异常帧在 MSP 还是 PSP
    ↓
从异常帧取 saved PC、LR、xPSR、R0–R3、R12
    ↓
读取 SCB->CFSR、HFSR、BFAR、MMFAR（若内核支持）
    ↓
用 ELF + addr2line / GDB / IDE 解析 PC 和调用链
    ↓
确认非法访问、除零、栈溢出、坏函数指针或 MPU 违规等根因
```

| 信息 | 用途 |
| --- | --- |
| 保存的 `PC` | 定位异常相关指令，优先用带调试信息的 ELF 解析 |
| `SP`、MSP、PSP | 判断使用的栈及栈越界风险 |
| `CFSR` | MemManage、BusFault、UsageFault 的细分状态 |
| `HFSR` | HardFault 强制升级等信息 |
| `BFAR` / `MMFAR` | 状态位标明地址有效时，提供出错访问地址 |

`PC` 不一定就是最初根因所在行：栈早已被写坏、函数指针被破坏或延迟总线错误，都可能稍后才触发 Fault。因此还要检查栈边界、调用链、状态位和最近的内存写入。

## 9. 指令状态、保护与性能

### 9.1 Thumb / Thumb-2

Cortex-M 只执行 Thumb/Thumb-2 指令。函数地址常见 `0x08001235`：最低位 `1` 表示 Thumb 状态，实际指令地址对齐到 `0x08001234`。错误构造函数指针时丢失该状态位，可能导致跳转失败或 UsageFault。

### 9.2 MPU、Cache、DMA 与屏障

`MPU`（Memory Protection Unit）可限制任务对 RAM、外设和执行区域的访问，违规可能产生 MemManage Fault。M23/M33 等 ARMv8-M 内核还可能支持 TrustZone。是否具备、区域数量和限制条件均依内核而定。

M7 等内核可能带 D-Cache，而 DMA 常直接访问 RAM：

```text
CPU 写数据 → D-Cache（尚未回写 RAM） → DMA 可能读到旧数据
DMA 写 RAM → CPU 仍从 D-Cache 读     → CPU 可能读到旧数据
```

根据 DMA 方向和内存属性，在合适边界 Clean（写回）或 Invalidate（失效）D-Cache，或把缓冲区放入 non-cacheable 区域。缓存维护要考虑缓存行对齐和范围，避免误影响相邻数据。

| 指令 | 粗略理解 |
| --- | --- |
| `DMB` | 保证屏障前后的显式内存访问顺序 |
| `DSB` | 等待屏障前的显式内存访问完成 |
| `ISB` | 刷新后续取指，使处理器重新观察执行环境 |

它们常见于 Cache、MPU、外设配置和异常控制代码；应按 ARM 架构手册及 SDK 的推荐序列使用，不能替代锁或临界区设计。

## 10. 调试与学习路径

```text
PC 上的 IDE / GDB → J-Link / ST-Link → SWD（或 JTAG）→ Cortex-M
```

调试接口可用于断点、单步、读寄存器/内存、查看调用栈和 Watchpoint。量产故障建议保留 ELF、map 文件、固件版本与可解析的崩溃现场。

| 阶段 | 建议掌握 | 能解决的问题 |
| --- | --- | --- |
| 基础 | `PC/LR/SP`、MSP/PSP、向量表、启动流程、Flash/RAM、`.text/.data/.bss` | 看懂启动和变量位置 |
| 中断与 RTOS | Thread/Handler、NVIC、优先级、异常帧、SysTick/SVC/PendSV、`BASEPRI` | 解释中断、临界区和任务切换 |
| 定位与进阶 | HardFault、ELF 解析、MPU、Cache/DMA、屏障、汇编/ABI/链接脚本 | 定位跑飞、内存访问和数据一致性问题 |

## 11. 一页速记

```text
Cortex-M
├── 执行：R0–R15、PC、LR、SP、xPSR
│   └── 栈：MSP（异常）/ PSP（常见 RTOS 任务）
├── 启动：向量表 → Reset_Handler → .data/.bss → main()
├── 异常：NVIC → 自动异常帧 → ISR → 异常返回
│   ├── SysTick / SVC / PendSV：RTOS 常用三件套
│   └── HardFault：PC + CFSR/HFSR + 栈 + ELF 定位
├── 内存：Flash、RAM、stack、heap、MPU
└── 进阶：Thumb、FPU、Cache、DMA、Barrier、SWD/GDB
```

最值得优先串起来的一条链路是：**异常栈帧 → MSP/PSP → PendSV → 上下文切换 → HardFault 现场解析。** 掌握它后，Cortex-M 与 FreeRTOS 的零散知识会变成一套可用于调试的机制。
