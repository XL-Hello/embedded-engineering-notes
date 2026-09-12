# 嵌入式 C 语言：内存布局、启动文件和链接脚本

> 目标：不仅知道 `.text`、`.data`、`.bss` 分别放什么，还要能解释上电后程序如何从复位向量走到 `main()`，并能读懂、修改链接脚本中的 Flash/RAM 分区、段放置和栈堆边界。本文以 Cortex-M + GNU Arm 工具链为主，概念同样适用于多数裸机 MCU。

---

## 1. 先看全貌：从源文件到 `main`

一个 C 源文件不会直接变成可烧录到 MCU 的镜像，大致经历下面的过程：

```text
main.c / driver.c
       │ 编译、汇编
       ▼
main.o / driver.o（可重定位目标文件，带有各自的段和符号）
       │ 链接脚本决定最终地址、合并段、解决符号
       ▼
firmware.elf（调试信息、段、符号齐全）
       │ objcopy
       ▼
firmware.bin / firmware.hex（烧录文件）
       │ 复位后取向量表
       ▼
Reset_Handler → 复制 .data → 清零 .bss → 运行库初始化 → main()
```

需要区分三类“地址/文件”：

| 名称 | 含义 | 常见位置 |
|---|---|---|
| ELF | 链接后的完整程序映像，含符号和调试信息 | PC 构建目录 |
| 加载地址（LMA） | 初始内容存放的位置，通常在 Flash | `.data` 的初值 |
| 运行地址（VMA） | CPU 运行时访问的位置 | `.data` 在 RAM 中的地址 |

`.data` 正是 LMA 与 VMA 不同的典型例子：初值烧在 Flash，启动时复制到 RAM，之后变量才能修改。

---

## 2. C 对象的存储期与内存段不是一回事，但密切相关

C 语言先定义对象的**存储期**；编译器和链接器再把对象放入合适的段。常见对应关系如下：

| C 对象 | 存储期 | 常见段 | 是否有初值 |
|---|---|---|---|
| 函数、字符串字面量、`const` 常量 | 静态 | `.text` / `.rodata` | 位于 Flash |
| 已初始化的全局变量、`static` 变量 | 静态 | `.data` | 初值在 Flash，运行于 RAM |
| 未初始化或初始化为 0 的全局/静态变量 | 静态 | `.bss` | RAM 上电后由启动代码清零 |
| 普通局部变量、形参、返回地址 | 自动 | 栈（stack） | 进入作用域时建立 |
| `malloc()` 得到的对象 | 动态 | 堆（heap） | 运行时分配 |

```c
int g_count = 3;                 /* .data */
int g_ready;                     /* .bss */
static uint8_t cache[256];       /* .bss */
const uint32_t baud = 115200U;   /* 常见为 .rodata；实现可优化掉 */

void demo(int arg)
{
    int local = arg + 1;         /* 通常在栈上，可能被优化到寄存器 */
    static int calls;            /* .bss，只初始化一次且跨调用保留 */
    ++calls;
}
```

段名是工具链约定，不是 C 标准的一部分。开启优化后，未使用对象可能被删除，局部变量也未必真的有栈地址；调试时不能把“源代码中的变量”机械等同为“一块固定内存”。

---

## 3. 常见段及其真正含义

### 3.1 `.text`：机器指令

`.text` 保存可执行代码，通常位于 Flash。只读程序存储器上的代码不消耗 RAM；但若 MCU 从 RAM 执行代码，或链接脚本把函数放进 RAM，则例外。

### 3.2 `.rodata`：只读数据

字符串字面量、查找表和大多数只读常量会放入 `.rodata`，一般紧邻 `.text` 并存于 Flash：

```c
static const uint16_t sine_table[] = {0, 125, 249, 368};
const char version[] = "v1.2.0";
```

`const` 的语义是“不能通过该名字修改”，并不绝对保证放入 Flash。例如 `const` 局部变量可能被编译器直接替换为立即数；外设寄存器常用的 `volatile const` 则是只读的 RAM/外设地址。

### 3.3 `.data`：有初值、可修改的静态对象

```c
uint32_t g_baud = 115200U;
static uint8_t state = 1U;
```

这类变量既占 Flash（保存初值）又占 RAM（运行时实体）。所以“给全局变量一个非零初值”会同时增加镜像大小和 RAM 占用。

### 3.4 `.bss`：零初始化的静态对象

```c
uint8_t rx_buffer[1024];
static bool initialized;
```

`.bss` 在 ELF 中记录长度而不保存大量 0 字节，因此不显著增加 bin/hex 体积，但一定占 RAM。C 规定静态存储期对象默认初始化为 0；这是启动代码清零 `.bss` 后才成立的。

### 3.5 `COMMON`：旧式“暂定定义”的坑

不要在头文件中写 `int g_flag;` 并被多个 `.c` 包含。它可能造成多重定义，历史上某些编译选项还会将其作为 COMMON 符号合并，掩盖问题。头文件只声明，恰好一个源文件定义：

```c
/* module.h */
extern int g_flag;

/* module.c */
int g_flag;
```

---

## 4. Flash 与 RAM 的典型布局

以常见 Cortex-M 为例，Flash 从 `0x08000000`、SRAM 从 `0x20000000` 开始只是芯片厂商的常见映射；最终必须以芯片手册和链接脚本为准。

```text
Flash
低地址  [ 向量表 ][ .text ][ .rodata ][ .data 初值 ]
高地址

RAM
低地址  [ .data ][ .bss ][ heap -->       <-- stack ] 高地址
```

栈通常从 RAM 高地址向低地址增长；堆通常从低地址向高地址增长。它们相撞时就是堆栈溢出。不要仅凭“程序还能启动”判断安全：栈越界常常先破坏 `.bss` 或其他任务栈，症状会出现在很晚以后。

可用链接器提供的符号观察边界：

```c
extern uint8_t _sdata, _edata, _sbss, _ebss;
extern uint8_t _estack, _end;

/* 地址应通过 &符号取得；这些不是普通可读写变量。 */
uintptr_t ram_used_static = (uintptr_t)&_ebss - (uintptr_t)&_sdata;
```

符号名称完全取决于脚本，常见的还有 `_sidata`、`__StackTop`、`__HeapLimit`。

---

## 5. 上电复位后：向量表和启动文件

### 5.1 向量表的前两项

Cortex-M 复位后，硬件从向量表读取：

1. 第 0 项：主栈指针 MSP 的初值；
2. 第 1 项：复位处理函数 `Reset_Handler` 的地址。

之后的表项依次是 NMI、HardFault、SysTick 和各外设中断入口。Cortex-M 的 Thumb 函数地址最低位为 1，工具链在生成向量表时会正确处理；不要手工清掉该位。

简化的 GNU 汇编写法：

```asm
.section .isr_vector, "a", %progbits
.word _estack
.word Reset_Handler
.word NMI_Handler
.word HardFault_Handler
```

向量表必须位于芯片复位能取到的位置，或由 BootROM/Bootloader 配置后重定位。带 Bootloader 的应用程序往往不从 Flash 起始地址链接，且需要设置 `SCB->VTOR` 指向应用自己的向量表。

### 5.2 `Reset_Handler` 做了什么

最小化流程如下：

```c
extern uint32_t _sidata, _sdata, _edata;
extern uint32_t _sbss, _ebss;

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    uint32_t *dst = &_sdata;

    while (dst < &_edata) {
        *dst++ = *src++;         /* Flash → RAM：建立 .data */
    }
    for (dst = &_sbss; dst < &_ebss; ) {
        *dst++ = 0U;             /* 清零 .bss */
    }

    SystemInit();                /* 时钟、FPU、向量表等芯片相关配置 */
    __libc_init_array();         /* C++ 构造函数；纯 C 工程也可能需要 */
    (void)main();
    while (1) { }
}
```

实际工程通常由芯片 SDK 提供启动文件。修改前先确认运行库是否已完成数据段初始化，避免重复或遗漏。若使用 C++，遗漏 `__libc_init_array()` 会导致全局对象构造函数没有运行。

### 5.3 弱符号：默认中断处理函数

启动文件常为每个中断提供弱定义：

```c
void Default_Handler(void)
{
    while (1) { }
}

void USART1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
```

应用中只要提供同名的普通（强）定义，就会覆盖弱定义：

```c
void USART1_IRQHandler(void)
{
    /* 读取状态、清中断标志、处理数据 */
}
```

函数名、签名和向量表项必须完全匹配；写成了另一个名字，链接仍可能成功，却会在中断发生后进入 `Default_Handler`。

---

## 6. 链接脚本：把“段”放进真实存储器

GNU ld 脚本通常有两层：`MEMORY` 描述芯片物理可用区域，`SECTIONS` 决定输出段如何放置。

```ld
MEMORY
{
  FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 512K
  RAM   (xrw) : ORIGIN = 0x20000000, LENGTH = 128K
}

ENTRY(Reset_Handler)

SECTIONS
{
  .isr_vector :
  {
    KEEP(*(.isr_vector))
  } > FLASH

  .text :
  {
    *(.text .text.*)
    *(.rodata .rodata.*)
    . = ALIGN(4);
    _etext = .;
  } > FLASH

  _sidata = LOADADDR(.data);
  .data : AT(_etext)
  {
    _sdata = .;
    *(.data .data.*)
    . = ALIGN(4);
    _edata = .;
  } > RAM

  .bss (NOLOAD) :
  {
    _sbss = .;
    *(.bss .bss.*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
  } > RAM
}
```

### 6.1 `> RAM`、`AT(...)` 与 `LOADADDR`

`.data > RAM` 指定运行地址在 RAM；`AT(_etext)` 指定其初始字节在 Flash 中紧跟 `.text`。`LOADADDR(.data)` 取得这份初值的 Flash 地址，供复位代码复制。若没有 `AT`，`.data` 的加载地址通常也会落在 RAM，烧录镜像中就没有可复制的初值。

### 6.2 `KEEP`：防止向量表被垃圾回收

使用 `-ffunction-sections -fdata-sections` 配合 `--gc-sections` 时，链接器会删除它认为未引用的输入段。向量表可能没有常规 C 引用，因此要用：

```ld
KEEP(*(.isr_vector))
```

同理，注册表、启动钩子和特殊元数据段也常需 `KEEP`。但不要对所有段一概 KEEP，否则会失去减小镜像的效果。

### 6.3 `ALIGN`：不仅为了好看

许多 MCU/总线要求 2、4 或更高字节对齐；向量表还可能有更严格的对齐要求。脚本中的 `. = ALIGN(4);` 让下一个对象从 4 字节边界开始。错误对齐可能导致访问异常、性能下降，或者在更换编译优化级别后才暴露。

---

## 7. 自定义段：把对象放到指定位置

### 7.1 典型需求

- DMA 缓冲区：放进 DMA 可访问的 SRAM，且满足缓存和对齐要求；
- 不初始化数据：软件复位后保留诊断信息；
- 快速函数：从 RAM 执行以降低 Flash 等待周期或避免擦写 Flash 时停顿；
- 固件信息：放在固定 Flash 偏移供 Bootloader 校验。

源文件中标记段：

```c
uint8_t dma_rx[512]
    __attribute__((section(".dma_buffer"), aligned(32)));

uint32_t reset_reason
    __attribute__((section(".noinit")));
```

脚本中接住它们：

```ld
.dma_buffer (NOLOAD) : ALIGN(32)
{
  *(.dma_buffer)
} > RAM

.noinit (NOLOAD) :
{
  *(.noinit .noinit.*)
} > RAM
```

`NOLOAD` 表示镜像不需要为该段提供加载内容；它不等于“自动安全保留”。启动代码若把整个 RAM 清零、看门狗复位实际变成掉电复位，或链接地址改变，数据仍会失效。使用前应定义魔数、版本和校验，并明确哪些复位路径可以保留。

---

## 8. 栈、堆与 `malloc`

### 8.1 栈溢出的表现

深层调用、大数组局部变量、递归、格式化打印和中断嵌套都会增加栈深度：

```c
void bad_example(void)
{
    uint8_t frame[2048]; /* 很容易压垮小 RAM MCU 的栈 */
    use(frame);
}
```

优先将大缓冲区设计为受控的静态对象、调用者提供的缓冲区或 RTOS 任务专用缓冲区；不要仅仅把它改成全局变量而不评估并发访问。

### 8.2 为什么裸机中慎用动态分配

`malloc()` 需要堆区和 `_sbrk` 等系统调用桩；长期运行还可能产生碎片。中断中绝不能调用常规 `malloc/free`，因为它们通常不是中断安全、也不保证实时性。

对于确定资源上限的嵌入式系统，优先选择静态分配、对象池或 RTOS 的固定块内存池。若必须使用堆，至少要明确堆边界、失败处理、并发保护和最大生命周期。

---

## 9. 如何验证：不要只看代码，要看产物

### 9.1 map 文件是内存问题的第一现场

链接时增加 `-Wl,-Map=firmware.map,--cref`。map 文件可回答：

- 哪个目标文件/符号占用了最大的 `.bss`、`.data`、`.rodata`；
- 某函数或数组最终放到了哪个地址；
- 某个库为何被拉入；
- 栈顶、堆起点和 RAM 余量在哪里。

### 9.2 常用命令

```sh
arm-none-eabi-size firmware.elf
arm-none-eabi-nm -n --size-sort firmware.elf
arm-none-eabi-objdump -h -S firmware.elf
arm-none-eabi-readelf -S -s firmware.elf
```

`size` 的 `text` 列常把 `.text`、`.rodata` 等 Flash 只读内容合计显示；`data` 表示需要初值的可写数据；`bss` 表示零初始化数据。不同工具版本的统计口径可能略有差异，定位问题时以 map 和 ELF 段表为准。

---

## 10. 常见问题排查清单

| 现象 | 优先检查 |
|---|---|
| 全局变量上电后不是 0 | `.bss` 是否清零；启动文件是否被正确链接；调试器是否复位后停在异常路径 |
| 已初始化变量值错误 | `.data` 的 LMA/VMA 与复制边界 `_sidata/_sdata/_edata` 是否匹配 |
| 程序一复位就进 HardFault | 向量表地址、初始 MSP、`Reset_Handler`、Flash/RAM 长度和链接地址 |
| 某中断进默认死循环 | 中断函数名称、向量表项、弱符号覆盖、是否清除了外设中断源 |
| RAM “明明够用”却偶发异常 | 栈深度、中断嵌套、DMA/Cache 对齐、堆栈碰撞、数组越界 |
| 烧录后无法启动 Bootloader 应用 | 应用的 Flash 起始地址、VTOR 重定位、向量表偏移、擦除页边界 |
| 自定义段变量无效 | 源文件 section 名与脚本是否一致；是否被 `--gc-sections` 删除；区域是否足够 |

---

## 11. 实战原则

1. 把链接脚本、启动文件和芯片内存图当作同一份设计的一部分；改了其中一个，就复核另外两个。
2. 每次发布固件都保留 ELF 和 map 文件；bin/hex 只能烧录，难以解释内存问题。
3. 大数组先问“是否真的需要 RAM、是否需要非零初值、是否需要一直常驻”。
4. 不要依赖未明确的启动顺序；时钟、Cache、FPU、外设和 C 运行库初始化要有清晰责任边界。
5. `__attribute__`、段名和链接符号均有工具链差异；迁移 IAR/Keil/GCC 时必须核对对应语法与启动流程。

掌握这条链路后，很多看似神秘的问题都会变得可定位：变量为何变成 0、初始化为何失效、函数为何没被调用、RAM 为何超限，本质上都能回到“对象在哪个段、何时被初始化、最终被放到哪个物理地址”。
