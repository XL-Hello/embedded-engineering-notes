# Cortex-M HardFault 基础知识总结

> 目标：这篇文档用于 Cortex-M HardFault 的入门、项目定位和面试复习。重点记住：HardFault 是什么、怎样保留崩溃现场、如何用 PC 与 Fault 寄存器定位根因，以及 RTOS 场景要额外看什么。
>
> 来源：围绕 HardFault、MSP/PSP 和 RTOS 异常机制整理的学习笔记，仅供参考。

## 1. 先用一句话理解 HardFault

**HardFault 是 Cortex-M 检测到严重异常后进入的异常处理函数；定位重点不是“修 HardFault”，而是找出触发它的第一处错误。**

可以先按下面的流程理解：

```text
发生异常
   -> 保存异常现场
   -> 读取 PC / LR
   -> 查看 CFSR、HFSR、BFAR、MMFAR
   -> 定位源代码和访问地址
   -> 修复根因并复测
```

常见根因包括：

- 空指针、野指针或非法地址访问。
- 数组越界、内存踩踏。
- 任务栈或中断栈溢出。
- 错误的函数指针或返回地址被破坏。
- 非对齐访问、非法指令等用法错误。
- 中断中调用了不应调用的阻塞或非 ISR 安全接口。

直白说法：

> HardFault 更像 CPU 留下的一张“崩溃现场单”。PC 告诉你崩在哪条指令，Fault 状态寄存器告诉你为什么崩，地址寄存器常能告诉你访问了哪里。

## 2. HardFault 和其他 Fault 的关系

Cortex-M 的可配置 Fault 主要分为三类：

| Fault | 常见含义 | 典型问题 |
| --- | --- | --- |
| MemManage Fault | MPU/内存保护违规 | 越权访问、执行禁止区域 |
| BusFault | 总线访问错误 | 无效地址、外设/总线错误 |
| UsageFault | 指令或用法错误 | 非对齐访问、非法指令、除零 |
| HardFault | 严重 Fault 或强制升级后的异常 | 上述 Fault 未使能、无法继续处理等 |

很多芯片或工程默认没有单独使能 MemManage、BusFault、UsageFault。此时它们常会升级为 HardFault，因此 HardFault 并不等于“只有一种错误”。

## 3. 进入 HardFault 时 CPU 保存了什么

异常进入时，硬件会自动把一部分寄存器压入**异常发生前正在使用的栈**：线程模式若使用 PSP 就压入 PSP，若使用 MSP 就压入 MSP。随后处理函数在 Handler mode 下使用 MSP 运行。

基本异常栈帧通常包含：

```text
stack[0]  R0
stack[1]  R1
stack[2]  R2
stack[3]  R3
stack[4]  R12
stack[5]  LR
stack[6]  PC
stack[7]  xPSR
```

其中最值得关注的是：

| 字段 | 用途 |
| --- | --- |
| `PC` | 出错时正在执行或即将执行的位置，用于映射到源代码 |
| `LR` | 返回路径和调用线索；异常入口的 LR 还带有 EXC_RETURN 信息 |
| `xPSR` | 可辅助判断 Thumb 状态、活动异常等 |
| 原始 SP | 判断栈是否越界、现场是否可信 |

> 注意：如果启用了 FPU 且异常现场包含浮点扩展帧，栈帧布局会更长。实际定位时要结合芯片内核与工程的 FPU 配置确认。

## 4. 怎样保存并打印异常现场

常用做法是让汇编入口根据异常返回值 `LR` 判断异常前使用的是 MSP 还是 PSP，再把对应的栈指针传给 C 函数。

```c
void HardFault_Handler(void)
{
    __asm volatile(
        "TST lr, #4       \n"
        "ITE EQ           \n"
        "MRSEQ r0, msp    \n"
        "MRSNE r0, psp    \n"
        "B hardfault_c    \n"
    );
}

void hardfault_c(uint32_t *stack)
{
    uint32_t lr  = stack[5];
    uint32_t pc  = stack[6];
    uint32_t psr = stack[7];

    /* 将 pc、lr、psr 和 Fault 寄存器输出或保存到非易失存储。 */
}
```

实际工程建议至少记录：

```text
PC、LR、xPSR、异常前 SP、CFSR、HFSR、MMFAR、BFAR、当前任务名
```

注意：

- HardFault 里不要依赖可能再次崩溃的复杂日志链路。
- 若使用 `printf`，确认其不会依赖锁、堆分配、DMA 或中断；更稳妥的是写入静态 RAM 缓冲区。
- 不要在不清楚根因时简单清状态寄存器并返回，否则可能反复异常或破坏现场。

## 5. Fault 状态寄存器怎么看

`SCB->CFSR` 是最关键的状态寄存器，它组合了 MemManage、BusFault 和 UsageFault 的状态位。`SCB->HFSR` 用来判断是否发生 HardFault 或被强制升级。

| 寄存器 | 作用 | 排查重点 |
| --- | --- | --- |
| `SCB->CFSR` | 三类可配置 Fault 的状态位 | 先看具体哪一类、哪个状态位置位 |
| `SCB->HFSR` | HardFault 状态 | `FORCED` 常表示其他 Fault 升级而来 |
| `SCB->MMFAR` | MemManage Fault 地址 | 仅在对应地址有效位为 1 时可信 |
| `SCB->BFAR` | BusFault 地址 | 仅在对应地址有效位为 1 时可信 |
| `SCB->AFSR` | 辅助 Fault 状态 | 是否有意义依赖具体内核和芯片实现 |

常见状态和思路：

| 现象 | 优先怀疑 |
| --- | --- |
| `HFSR.FORCED=1` | 继续拆解 `CFSR`，原始 Fault 多半在其中 |
| `CFSR` 有精确数据总线错误且 `BFARVALID=1` | 查看 `BFAR`，定位哪次读写访问了非法地址 |
| `CFSR` 有未定义指令/非法状态 | 函数指针跳飞、代码或栈被破坏 |
| `CFSR` 有非对齐访问 | 指针强转、packed 结构体、缓冲区偏移问题 |
| `CFSR` 有除零状态 | 检查除数及是否开启 `DIV_0_TRP` |

## 6. 用 PC 定位到具体代码

`PC` 是定位的第一入口。拿到 PC 后，优先用带调试信息的 ELF 文件查源文件和行号。

```bash
arm-none-eabi-addr2line -e firmware.elf -f -C 0x08012345
```

也可以在 GDB 中查看：

```bash
arm-none-eabi-gdb firmware.elf
(gdb) list *0x08012345
(gdb) info line *0x08012345
```

如果没有 ELF 或调试信息，可用 map 文件或反汇编确认该地址所在函数。

注意：

- 确认地址属于当前固件的 Flash、RAM 代码区还是无效区。
- 若 `PC` 落在 `0xFFFFFFxx`、明显空洞地址或不应执行的 RAM，优先怀疑函数指针、返回地址或栈被破坏。
- 优化编译下，源码行可能与实际指令不完全一一对应；结合反汇编和调用栈判断。

## 7. 常见 HardFault 原因

### 7.1 空指针或野指针

```c
int *p = NULL;
*p = 10;
```

这类问题常来自指针未初始化、对象已释放后继续使用、`malloc` 失败未检查，或结构体成员被覆盖。

排查：

- 查看故障指令的读写地址；若有效，结合 `BFAR/MMFAR`。
- 回溯该指针的来源、生命周期和边界检查。
- 对关键接口增加空指针断言。

### 7.2 数组越界和内存踩踏

```c
uint8_t buf[10];
buf[20] = 1;
```

越界未必立刻异常；它可能先覆盖局部变量、任务控制块、保存的 LR 或函数指针，稍后才因 PC 跳飞进入 HardFault。

排查：

- 关注最近修改过的缓冲区长度、`memcpy`、字符串操作和协议解析。
- 对长度字段做上限检查。
- 使用编译器告警、静态分析、栈哨兵或 MPU 辅助发现问题。

### 7.3 栈溢出

RTOS 中尤其常见：任务栈太小、递归过深、局部大数组、格式化打印消耗大量栈都会触发。

```c
void task(void)
{
    uint8_t buf[4096];
}
```

排查：

- 查看当前任务名、PSP、任务栈范围和 high-water mark。
- 查看 MSP 是否也充足：中断嵌套和异常处理使用 MSP。
- FreeRTOS 可启用 `configCHECK_FOR_STACK_OVERFLOW` 并定期检查剩余栈。

### 7.4 错误函数指针或返回地址损坏

```c
void (*func)(void);
func();
```

函数指针未初始化、回调对象已失效，或栈被踩导致返回地址损坏，都可能让 PC 跳到非法位置。

排查：

- 看 PC 是否属于合法可执行区域。
- 看 LR、调用点及回调注册/注销流程。
- 回查可能破坏栈的数组越界和错误 `memcpy`。

### 7.5 非对齐访问、非法指令和除零

```c
uint32_t *p = (uint32_t *)0x20000001;
*p = 10;
```

不同 Cortex-M 和配置对非对齐访问的容忍度不同；开启相应 trap 后会触发 UsageFault。结构体强制对齐、错误的字节流解析和不安全指针转换是常见来源。

### 7.6 中断上下文使用不当

在 ISR 中执行复杂、阻塞或非 ISR 安全的操作，可能造成栈耗尽、死锁、堆损坏或调度状态错误。

避免在中断中直接做：

- 长时间循环、延时等待。
- 常规 `malloc/free`。
- 不是 `FromISR` 版本的 RTOS 同步接口。
- 依赖锁或缓冲资源的复杂打印。

原则：**中断里只做快速取数、清标志、通知任务；复杂处理放到任务中。**

## 8. RTOS 场景要额外看什么

RTOS 下除了 PC 与 Fault 寄存器，还要检查当前任务和上下文切换相关信息：

| 检查项 | 为什么重要 |
| --- | --- |
| 当前任务名和任务栈范围 | 判断是否是特定任务的栈溢出或非法访问 |
| PSP | 线程模式任务栈的位置，现场通常从这里取得 |
| MSP | Handler mode、中断和异常处理栈，嵌套中断多时也可能溢出 |
| PendSV / SysTick 附近 PC | 可能涉及上下文保存恢复、TCB 或栈损坏 |
| 中断优先级与 RTOS 规则 | 不合规的 ISR API 调用可能破坏调度状态 |

### 8.1 MSP 和 PSP 是什么

Cortex-M 的 R13（栈指针 `SP`）有两个物理寄存器可选：`MSP` 和 `PSP`。它们都指向向低地址增长的栈，只是服务对象不同。

| 栈指针 | 全称 | 主要用途 |
| --- | --- | --- |
| `MSP` | Main Stack Pointer，主栈指针 | 复位后的启动代码、Handler mode、异常和中断处理 |
| `PSP` | Process Stack Pointer，进程栈指针 | Thread mode 下的应用线程；RTOS 任务通常用它 |

直白理解：

> MSP 是系统处理异常时用的栈，PSP 是任务正常执行时用的栈。RTOS 让每个任务拥有各自的 PSP 栈，从而隔离不同任务的局部变量和调用现场。

### 8.2 为什么 Cortex-M 需要两个栈

没有 RTOS 的简单裸机程序通常只用 MSP 也能运行。但在多任务系统中，一个任务的函数调用、局部变量和保存寄存器不能与其他任务混在同一块栈里。

```text
Task A 运行：PSP -> Task A Stack
Task B 运行：PSP -> Task B Stack

发生中断/异常：MSP -> System / Exception Stack
```

任务切换时，内核保存 Task A 的 PSP，并加载 Task B 的 PSP。于是 CPU 继续使用的 `SP` 就落在 Task B 的任务栈上；每个任务不需要共享同一个应用栈。

使用独立 MSP 的另一个目的，是让中断和异常处理不直接消耗当前任务的栈。这样任务栈接近耗尽时，Handler mode 仍通常有自己的 MSP 可运行并记录故障。

> 但这不是绝对保护：如果任务 PSP 已经损坏到无法完成异常自动压栈，或 MSP 本身也溢出，异常处理仍可能失败。

### 8.3 线程模式如何选择 MSP 或 PSP

Cortex-M 有两种处理器模式：

| 模式 | 可使用的栈 |
| --- | --- |
| Thread mode（正常执行应用/任务） | 可由 `CONTROL.SPSEL` 选择 MSP 或 PSP |
| Handler mode（执行异常/中断） | 固定使用 MSP |

`CONTROL` 寄存器的 `SPSEL` 位决定 Thread mode 使用哪个栈：

| `CONTROL.SPSEL` | Thread mode 的 `SP` |
| --- | --- |
| `0` | MSP |
| `1` | PSP |

系统复位后，Thread mode 默认使用 MSP。RTOS 创建任务并启动调度器后，通常设置 PSP 指向首个任务的栈顶，再将 `CONTROL.SPSEL` 设为 `1`。写入 `CONTROL` 后需要执行 `ISB`，确保后续指令使用新的栈选择。

```c
/* 示意代码：实际 RTOS 通常由端口层汇编完成。 */
__set_PSP((uint32_t)task_stack_top);
__set_CONTROL(__get_CONTROL() | 0x2U);  /* SPSEL = 1，Thread mode 使用 PSP */
__ISB();
```

### 8.4 异常发生时，现场到底压到哪里

这是 HardFault 定位最容易混淆的地方：**硬件自动压栈发生在切入 Handler mode 之前，因此压入的是异常发生前活动的栈。**

若任务在线程模式使用 PSP 时发生 HardFault，过程如下：

```text
Task A 正在运行（Thread mode，SP = PSP）
    -> CPU 将 R0-R3、R12、LR、PC、xPSR 自动压入 Task A 的 PSP 栈
    -> CPU 切入 Handler mode，SP 改为 MSP
    -> 执行 HardFault_Handler（使用 MSP）
```

若 Thread mode 本来使用 MSP，或异常嵌套在 Handler mode 中，则自动现场压入 MSP。

所以 HardFault 汇编入口会检查异常入口 `LR` 中的 `EXC_RETURN`：其 bit 2 为 `0` 表示基本现场在 MSP，为 `1` 表示基本现场在 PSP。这正是下面两条指令选择传给 `hardfault_c()` 的栈指针的原因：

```asm
TST lr, #4       ; 检查 EXC_RETURN 的 bit 2
MRSEQ r0, msp    ; bit 2 = 0：现场在 MSP
MRSNE r0, psp    ; bit 2 = 1：现场在 PSP
```

### 8.5 MSP/PSP 与 RTOS 上下文切换

以 FreeRTOS 一类 Cortex-M RTOS 为例，流程可概括为：

```text
上电复位
    -> MSP 指向启动栈，Reset_Handler / main() 使用 MSP
创建任务
    -> 为每个任务分配独立任务栈
启动调度器
    -> PSP 装载首个任务的栈顶，任务开始运行
SysTick 触发
    -> 进入 Handler mode，使用 MSP 执行 SysTick_Handler
PendSV 执行切换
    -> 保存旧任务剩余寄存器到旧 PSP 栈
    -> 将旧 PSP 写入旧任务 TCB，取出新任务 PSP
    -> 恢复新任务寄存器，异常返回后使用新 PSP 继续运行
```

硬件在异常入口自动保存 R0-R3、R12、LR、PC、xPSR；RTOS 的 PendSV 汇编通常再保存/恢复 R4-R11（有 FPU 时还包括相应浮点寄存器）。因此，**切换任务的本质就是保存旧任务的 PSP 和寄存器现场，再恢复新任务的 PSP 和寄存器现场。**

### 8.6 和 HardFault 定位的直接关系

发生 HardFault 时，不能只看当前 `MSP`：它是 Handler 自己正在使用的系统栈，未必是出错任务的现场栈。应按 `EXC_RETURN` 选择异常前的 MSP 或 PSP，才能正确取得压栈的 `PC`、`LR` 与 `xPSR`。

排查时可按下面的规则记忆：

- `EXC_RETURN` 指向 PSP：故障来自使用 PSP 的线程/任务，优先查当前任务栈、任务上下文和该任务访问的内存。
- `EXC_RETURN` 指向 MSP：故障可能发生在启动代码、未切 PSP 的线程，或中断/异常嵌套期间；优先查 MSP 栈和 ISR。
- 如果 HardFault 出现在 `PendSV_Handler` 附近，重点检查任务栈边界、TCB、上下文保存恢复代码，以及是否有内存踩踏。

## 9. 推荐的项目排查步骤

1. **停住现场。** 在 `HardFault_Handler` 打断点，避免复位后丢失信息。
2. **记录基础信息。** 保存 PC、LR、xPSR、MSP/PSP、CFSR、HFSR、MMFAR、BFAR、当前任务名。
3. **先查 PC。** 用 `addr2line`、GDB、map 文件和反汇编找到故障指令。
4. **再查 CFSR。** 区分访问错误、用法错误还是内存保护错误；有有效地址时查看 BFAR/MMFAR。
5. **核查指针与长度。** 检查该行相关的对象生命周期、数组边界和数据包长度。
6. **核查栈与上下文。** 看任务栈余量、MSP 余量、ISR 调用和 PendSV 附近是否异常。
7. **修复后复测。** 覆盖异常输入、长时间运行、最大负载和低内存等场景，确认不是偶然消失。

## 10. 工程中值得加的增强措施

### 10.1 持久化崩溃信息

不要只依赖串口打印。量产设备可把关键信息放到备份 RAM、保留 RAM、Flash/NVS 等位置，并在下次启动时上报。

建议最少保存：

```text
固件版本、复位原因、PC、LR、SP、CFSR、HFSR、MMFAR、BFAR、当前任务名
```

### 10.2 提前失败，而不是等到崩溃

```c
configASSERT(ptr != NULL);
```

对输入长度、状态机状态、指针和返回值加断言或错误处理，通常比等到内存踩踏后再进 HardFault 更容易定位。

### 10.3 使用栈和内存保护机制

- 打开 RTOS 栈溢出检查并监控 high-water mark。
- 对大数组改为静态缓冲或显式分配，并估算最坏栈深。
- 芯片支持时使用 MPU 把任务栈、堆和关键区域做访问保护。
- 保留编译器告警，结合静态分析检查未初始化指针和越界风险。

## 11. 高频易错点

| 错误说法 | 更准确的说法 |
| --- | --- |
| HardFault 就是某一个固定错误 | 它可能是其他 Fault 升级而来，需先看 CFSR/HFSR |
| 只看 HardFault_Handler 就能定位 | 核心是取到异常前的 PC、LR、SP 和 Fault 寄存器 |
| BFAR/MMFAR 一定有效 | 只有对应有效位表明地址有效时才可相信 |
| PC 在异常处理函数里就是出错位置 | 要取自动压栈的 `stack[6]`，而不是 Handler 自身 PC |
| 任务栈溢出一定立刻 HardFault | 常先破坏别的数据，稍后才以任意形式崩溃 |
| 异常都把现场压到 MSP | 现场压入异常发生前活动的栈；Handler 再使用 MSP 运行 |
| 清掉状态寄存器并返回就修好了 | 根因仍在，可能立刻再次异常或留下数据损坏 |

## 12. 面试常见问法和直白回答

### 12.1 遇到 HardFault 怎么定位

> 我会先在 HardFault_Handler 中保留异常现场，读取自动压栈的 PC、LR、xPSR 以及 CFSR、HFSR、BFAR、MMFAR。然后用 PC 配合 ELF、addr2line 或 map 文件定位到具体指令，再根据 CFSR 判断是非法访问、总线错误还是用法错误。如果有有效的 BFAR/MMFAR，就继续查实际访问地址。RTOS 下还会看当前任务、PSP/MSP、栈余量和 PendSV 上下文是否被破坏。

### 12.2 CFSR 和 HFSR 分别做什么

> CFSR 给出 MemManage、BusFault、UsageFault 的具体状态，是分析根因的重点；HFSR 表示 HardFault 状态，其中 FORCED 经常说明某个可配置 Fault 被升级成了 HardFault。

### 12.3 为什么要看 PC

> 自动压栈保存的 PC 最接近触发异常的指令地址。把它映射回 ELF 或源代码，才能知道究竟是哪一行代码发生了错误。

### 12.4 RTOS 下为什么还要看 MSP 和 PSP

> 任务通常在线程模式用 PSP，异常和中断处理在 Handler mode 用 MSP。HardFault 发生时，任务现场通常保留在异常前使用的任务栈上，而处理函数使用 MSP。因此要同时确认任务栈、异常栈和上下文切换是否正常。

## 13. 最简记忆版

- HardFault 不是根因，而是 Cortex-M 对严重异常的处理入口。
- 先取异常栈帧：`PC`、`LR`、`xPSR` 最关键。
- 再看 `CFSR`、`HFSR`；地址有效时看 `BFAR/MMFAR`。
- 用 `addr2line`、GDB、map 文件把 PC 映射回代码。
- 高频根因：空/野指针、越界、栈溢出、函数指针跳飞、非对齐访问和 ISR 使用不当。
- RTOS 下同时看当前任务、PSP、MSP、任务栈余量和 PendSV。
- 量产设备应保存崩溃信息，下一次启动后再上报。
