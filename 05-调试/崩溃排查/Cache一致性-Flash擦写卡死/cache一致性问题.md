# Cache 一致性、DMA 与 volatile 基础知识总结

> 目标：这篇文档用于理解嵌入式中 CPU Cache、DMA、外设、共享内存和 `volatile` 的关系。重点记住：哪些问题属于编译器优化，哪些属于 D-Cache 与内存不一致，何时该用同步原语、内存屏障或 Cache clean/invalidate。
>
> 来源：围绕 Cortex-M、ESP32 类 SoC、RTOS 与常见 DMA 外设场景整理的学习笔记，仅供参考。具体 Cache API、内存属性和 DMA 限制必须以芯片手册与 SDK 文档为准。

## 1. 先用一句话理解 Cache 一致性

**当多个执行主体访问同一块数据，而其中某一方看到的不是最新内容时，就出现了数据可见性或 Cache 一致性问题。**

典型结构如下：

```text
CPU  <->  D-Cache  <->  RAM  <->  DMA / 外设
                  ^
                  |
             其他 CPU 核
```

最常见的 DMA 问题是：CPU 写入的数据仍停留在 D-Cache，而 DMA 直接从 RAM 读取旧数据；或者 DMA 已写入 RAM，CPU 却仍从 D-Cache 读到旧数据。

先记住下面的分工：

| 概念 | 主要解决什么 | 不能替代什么 |
| --- | --- | --- |
| `volatile` | 防止编译器省略或合并对变量的访问 | 原子性、互斥、D-Cache 同步 |
| 原子操作/锁 | 多执行单元对共享数据的并发同步 | DMA 与 Cache 的数据同步 |
| 内存屏障 | 约束 CPU/编译器对内存访问的顺序 | 把脏 Cache 数据写回 RAM |
| Cache clean/invalidate | 同步 CPU Cache 与 RAM 中的数据副本 | 线程安全和协议设计 |
| DMA | 让外设直接读写内存，减少 CPU 搬运 | 自动维护 CPU D-Cache（通常不会） |

直白说法：

> `volatile` 管“编译器别自作主张”；锁和原子操作管“大家别抢着改”；Cache 维护管“CPU Cache 和 RAM 别各存一份不同的数据”。

## 2. 为什么 CPU 要有 Cache

CPU 的运行速度通常远快于片上 RAM、PSRAM 或 Flash。Cache 会保存近期访问过的指令或数据副本，以减少慢速存储访问。

```text
第一次读取：RAM / Flash -> Cache -> CPU
后续读取：               Cache -> CPU
```

Cache 提升了性能，但也带来副本问题：CPU 修改后的数据可能暂时只在 Cache 中，尚未写回 RAM；而 DMA、其他外设或其他 CPU 核访问的可能是 RAM 中的旧副本。

### 2.1 写回和写直达的区别

常见 Cache 写策略：

| 策略 | CPU 写数据后的表现 | DMA 风险 |
| --- | --- | --- |
| Write-back（写回） | 先更新 Cache，稍后再写回 RAM | 高，DMA 可能读到旧 RAM |
| Write-through（写直达） | 同时/很快写入 RAM | 仍需看平台规则，不能想当然省略同步 |

嵌入式 D-Cache 场景最常见的风险来自 write-back Cache。

## 3. I-Cache 和 D-Cache 分别是什么

| 类型 | 缓存内容 | 常见场景 | 主要一致性风险 |
| --- | --- | --- | --- |
| I-Cache（Instruction Cache） | CPU 即将执行的指令 | 从 Flash/XIP 执行代码 | 代码被修改后仍取到旧指令 |
| D-Cache（Data Cache） | CPU 读写的数据 | RAM、PSRAM、帧缓冲区 | CPU、DMA、外设看到的数据不同 |

对于 LCD、网卡、摄像头、音频等 DMA 场景，通常重点是 **D-Cache**。

I-Cache 的典型场景是 OTA、Flash 擦写、动态装载代码或在 RAM 中生成/修改可执行代码。代码内容被更新后，要遵循芯片/系统规定的指令同步流程；很多 SDK 会在 Flash 操作或固件切换中封装这些步骤，应用不应自行假设某个统一 API。

### 3.1 用 ESP32-S3 的内存布局理解 I-Cache / D-Cache

ESP32-S3 是理解 I-Cache 与 D-Cache 的好例子：常规应用的大部分代码和常量并不全部复制到内部 RAM，而是放在外部 SPI Flash 中，通过 MMU 和 Cache 映射后供 CPU 使用。ESP-IDF 中可以先这样理解：

| ESP-IDF 内存名 | 典型内容 | CPU 访问路径 | 和 Cache 的关系 |
| --- | --- | --- | --- |
| `IRAM` | 启动关键代码、IRAM-safe ISR、时间敏感函数 | CPU 指令总线直接访问内部 SRAM | 不依赖从 Flash 取指，适合 Cache 被关闭期间运行 |
| `IROM` | 默认的大部分应用代码 | SPI Flash -> MMU -> I-Cache -> CPU 取指 | 从 Flash 执行（XIP），Cache miss 时需从 Flash 取指 |
| `DRAM` | `.data`、`.bss`、普通堆、任务栈等 | CPU 数据总线访问内部 SRAM | 常规数据区；DMA 可访问性仍要看驱动和内存能力 |
| `DROM` | `const` 常量、只读查找表、字符串等 | SPI Flash -> MMU -> D-Cache -> CPU 读数据 | 只读数据从 Flash 映射读取 |
| `PSRAM`（启用时） | 大帧缓冲、图片、较大堆对象等 | 外部 RAM -> Cache/MMU -> CPU | 外部 RAM 通过 Cache 集成进地址空间，访问与内部 DRAM 的限制不同 |

```text
                         ESP32-S3

CPU 取指：  IROM 代码  <- I-Cache <- MMU <- SPI Flash
             ^
             |
           IRAM 代码（内部 SRAM，Cache 关闭时仍可执行）

CPU 读数据：DRAM 数据（内部 SRAM）
             DROM 常量 <- D-Cache <- MMU <- SPI Flash
             PSRAM 数据 <- D-Cache <- MMU <- 外部 PSRAM
```

这里要区分两个“RAM”概念：`IRAM`/`DRAM` 是片内 SRAM 的不同总线视图或用途；`IROM`/`DROM` 则通常是外部 Flash 经 MMU + Cache 映射得到的代码与只读数据区域。不能因为名字里都有 `ROM/RAM` 就把它们当成相同的物理存储。

### 3.2 ESP32-S3 的 I-Cache：为什么 Flash 操作会影响代码执行

默认情况下，普通函数通常放在 IROM：

```text
app_main() / 普通函数
    -> IROM 虚拟地址
    -> I-Cache 命中：CPU 直接取到指令
    -> I-Cache 未命中：Cache 通过 SPI0/1 从外部 Flash 取指
```

当代码擦写主 Flash 或在 SPI0/1 上进行会影响 Flash Cache 的操作时，普通 IROM 代码可能无法安全取指。ESP-IDF 会在相应 Flash API 中按配置处理 Cache 和并发限制；Cache 被关闭期间，CPU 必须执行位于 IRAM 的代码，并且只访问内部 DRAM 数据。

因此 ESP32-S3 项目中常见的 `IRAM_ATTR` 不只是“为了更快”，还常用于保证以下场景可运行：

- 注册为 IRAM-safe 的中断服务函数。
- Flash 擦写或 NVS/OTA 等可能影响 Flash Cache 的关键路径。
- 对响应延迟非常敏感、不希望承受 Flash Cache miss 的函数。

示意代码：

```c
void IRAM_ATTR gpio_isr_handler(void *arg)
{
    /* 只能调用同样位于 IRAM 的函数；
       使用的数据、字符串和查找表也要位于内部 DRAM。 */
}

static const char isr_tag[] DRAM_ATTR = "gpio";
```

> 重点：函数标记为 `IRAM_ATTR` 还不够。若 ISR 在 Cache 关闭时运行，它调用的函数、访问的常量字符串和全局数据也不能依赖 IROM/DROM/PSRAM；应按 ESP-IDF 的 IRAM-safe ISR 规则放入内部 IRAM/DRAM。

### 3.3 ESP32-S3 的 D-Cache：PSRAM、帧缓冲和 DMA

ESP32-S3 的外部 PSRAM 同样通过 Cache 集成到地址空间中。CPU 访问 PSRAM 时看起来像访问普通内存，但底层仍依赖外部 SPI RAM 和 Cache；当 Flash Cache 因 Flash 操作而不可用时，PSRAM 默认也不可访问。

以 LVGL + SPI LCD 为例，先分两种 buffer 放置位置理解：

```text
方案 A：绘制 buffer 在内部、DMA-capable SRAM
LVGL 写 buffer -> SPI DMA 发送 -> LCD

方案 B：大绘制 buffer 在 PSRAM
LVGL 写 PSRAM buffer -> 按 ESP-IDF/驱动能力处理传输
                  -> SPI DMA 发送 -> LCD
```

方案 B 的注意点更多：ESP32-S3 虽有外部 RAM DMA 支持，但 DMA 描述符不能放在 PSRAM，且 CPU 与 DMA 同时访问 PSRAM 时带宽会受限。不同 ESP-IDF 版本和具体外设驱动对 PSRAM DMA、bounce buffer、对齐和缓存维护的封装不同，因此不要仅凭“地址在 PSRAM”就手动套用其他 Cortex-M 的 `clean/invalidate` 流程。

工程建议：

- 优先让驱动管理 DMA 映射与同步；查看该驱动对 PSRAM buffer 的支持说明。
- 为直接 DMA 的 buffer 使用 `heap_caps_malloc()` 和正确的 capability（例如 `MALLOC_CAP_DMA`），而不是假设普通 `malloc()` 的内存都可 DMA。
- 大图或帧缓冲可以放 PSRAM，但 SPI DMA 描述符、时序关键的小 buffer、Cache 关闭期间使用的数据应放内部 RAM。
- Flash 擦写期间不要访问 PSRAM；任务栈默认也不应放在 PSRAM，除非已按 ESP-IDF 的专门配置和限制处理。

### 3.4 ESP32-S3 两个容易混淆的实例

#### 实例 1：OTA / NVS 写 Flash 时的 I-Cache 问题

```text
普通业务代码在 IROM，常量字符串在 DROM
    -> 调用 Flash 擦写 API
    -> 该操作可能使 Flash Cache 暂时不可用（具体行为取决于 IDF 配置）
    -> 此时若 ISR 或回调跳去执行 IROM 函数，或读取 DROM 字符串
    -> 可能触发异常、延迟抖动或访问限制问题
```

处理方式不是应用手动“刷新 I-Cache”后继续运行，而是遵守 ESP-IDF 的 Flash 并发规则：使用官方 Flash API；对必须在此期间响应的 ISR，使用 IRAM-safe 设计；避免在其路径上访问 Flash/PSRAM 映射的数据。

#### 实例 2：LVGL 大帧缓冲放 PSRAM 的 D-Cache / DMA 问题

```text
LVGL 在 CPU 上绘制
    -> 像素数据放在 PSRAM 映射区
    -> SPI 外设通过 DMA 发送给 LCD
    -> 驱动需保证 DMA 取得正确像素，且 buffer 在传输结束前不被 LVGL 覆盖
```

若出现局部旧图、花屏或偶发撕裂，排查不能只盯着 Cache：还要确认 buffer 是否 DMA-capable、是否需要驱动的 bounce buffer、DMA 描述符位置、传输期间 buffer 的所有权，以及双缓冲/flush 回调时序。对于 ESP-IDF 已支持的高层驱动，优先使用其推荐的内存类型和同步路径，而不是随意加入 `volatile`。

## 4. `volatile` 到底解决什么

`volatile` 告诉编译器：该对象的值可能在当前代码不可见的地方变化，每次访问都应按 volatile 语义实际生成读写操作，不能把值长期保存在寄存器中或随意删除访问。

```c
volatile uint8_t rx_done;

void UART_IRQHandler(void)
{
    rx_done = 1;
}

void task(void)
{
    while (!rx_done) {
        /* 等待中断修改标志。 */
    }
    process_data();
}
```

常见用途：

- 外设寄存器（通常由芯片头文件定义）。
- 被中断、硬件或调试器异步改变的简单状态。
- 极其简单的轮询标志；多线程场景更应使用原子操作或 RTOS 同步机制。

### 4.1 `volatile` 不保证什么

```c
volatile int count;
count++;
```

`count++` 仍是“读 -> 修改 -> 写”的多步操作，两个任务/核同时执行仍会丢更新。因此 `volatile` 不保证：

- 原子性。
- 互斥与线程安全。
- 多核同步协议。
- CPU 与 DMA 之间的 D-Cache 一致性。
- 内存访问顺序。

> 对多线程共享状态，优先使用 C 原子类型、RTOS 互斥锁/信号量或平台提供的同步原语；对 ISR 与任务通信，使用对应的 ISR 安全接口。

## 5. Cache 维护的两个基本动作

不同 SDK 的 API 名称不同，常见概念如下：

| 动作 | 常见别名 | 作用 |
| --- | --- | --- |
| Clean | Flush、write-back | 将 D-Cache 中的脏数据写回 RAM，Cache 副本仍可保留 |
| Invalidate | 丢弃、失效 | 丢弃 Cache 副本；CPU 下次读取会重新从 RAM 获取 |
| Clean + Invalidate | 清理并失效 | 先避免丢失脏数据，再丢弃副本 |

### 5.1 CPU 写，DMA 读：先 Clean

以 SPI/LCD 发送帧缓冲为例：

```text
CPU 绘制新图像
    -> 新像素可能只在 D-Cache 中
    -> Clean 对应缓冲区
    -> DMA 从 RAM 读取最新图像
    -> SPI / LCD 发送
```

若不 clean，DMA 可能从 RAM 取到上一帧内容，表现为旧图、花屏或偶发数据错误。

### 5.2 DMA 写，CPU 读：完成后 Invalidate

以 UART、网卡或摄像头接收为例：

```text
DMA 写入 RAM
    -> D-Cache 可能仍保留旧数据
    -> DMA 完成后 Invalidate 对应缓冲区
    -> CPU 重新从 RAM 读取新数据
```

若不 invalidate，CPU 可能持续读到接收前的旧数据。

### 5.3 DMA 接收前为什么有时还要处理 Cache

DMA 即将写入接收缓冲区时，如果该区域在 D-Cache 中有脏 Cache line，之后的回写可能覆盖 DMA 已经写入 RAM 的新数据。因此许多平台的推荐顺序是：

```text
DMA 接收前：Clean + Invalidate（或使用 SDK 的 dma_sync_for_device）
DMA 接收后：Invalidate（或使用 SDK 的 dma_sync_for_cpu）
```

确切动作由平台 DMA API 的所有权规则决定。原则是：**将缓冲区交给 DMA 前，CPU 不再持有脏副本；DMA 交还 CPU 后，CPU 不再使用旧副本。**

## 6. DMA + D-Cache 的标准流程

### 6.1 DMA 发送：Memory -> Peripheral

```text
CPU 填充发送 buffer
    -> Clean buffer 到 RAM
    -> （必要时内存屏障，确保维护操作完成）
    -> 启动 DMA
    -> DMA 读取 RAM 并发送到外设
```

伪代码：

```c
fill_tx_buffer(tx_buf, len);
cache_clean(tx_buf, len);       /* 平台相关 API */
memory_barrier_if_required();
dma_start_tx(tx_buf, len);
```

DMA 未完成前，CPU 不应修改该发送缓冲区；否则外设可能读到前后混合的数据。需要并行发送时，使用双缓冲、队列或明确的 buffer 所有权。

### 6.2 DMA 接收：Peripheral -> Memory

```text
CPU 准备接收 buffer
    -> 按平台要求 Clean + Invalidate
    -> 启动 DMA
    -> DMA 写 RAM
    -> DMA 完成中断
    -> Invalidate buffer
    -> CPU 读取新数据
```

伪代码：

```c
cache_clean_invalidate(rx_buf, RX_SIZE); /* 交给 DMA 前，平台相关 */
memory_barrier_if_required();
dma_start_rx(rx_buf, RX_SIZE);

/* DMA 完成后： */
cache_invalidate(rx_buf, received_len);
process_rx_buffer(rx_buf, received_len);
```

### 6.3 缓存行对齐是隐藏风险

Cache 操作通常以 **Cache line** 为最小单位，而不是任意一个字节。若缓冲区起止地址未按缓存行对齐，清理/失效时可能连带影响相邻变量。

```text
| 相邻变量 |      DMA buffer      | 相邻变量 |
^                         ^
Cache line 边界不对齐时，操作范围可能覆盖到相邻数据
```

建议：

- DMA buffer 按芯片的 Cache line 大小对齐。
- 分配长度向 Cache line 大小取整。
- 不要让 DMA buffer 与经常修改的普通变量共享同一 Cache line。
- 使用 SDK 提供的 DMA buffer 分配器或 `dma_map/sync` 接口，避免手写错误的范围计算。

## 7. 多核、共享内存和内存屏障

### 7.1 多核不等于一定要手动 flush Cache

部分 SoC（例如常见应用处理器）有硬件 Cache 一致性互连，CPU 核之间会自动维护同一普通内存的 Cache 一致性；部分 MCU/异构系统则不一定具备，需按平台手册使用非缓存区、共享内存属性或软件维护。

即使硬件 Cache 一致，多核仍需要**同步和内存顺序**：一个核写完数据后再发布 `ready` 标志，另一个核不能只依赖普通变量读写来保证“数据先于标志可见”。应使用原子操作、锁、消息队列或平台 IPC，必要时配合 acquire/release 语义与内存屏障。

```text
生产者：写 data -> release 发布 ready
消费者：acquire 观察 ready -> 读取 data
```

### 7.2 共享内存 IPC

进程或核映射同一块物理内存时，首先区分两件事：

- **Cache 属性**：映射是可缓存、不可缓存还是硬件一致。
- **同步协议**：谁拥有 buffer、何时写完、何时允许对方读。

Linux 用户态共享内存通常运行在硬件缓存一致的平台上，不需要应用手动 flush；但仍要用 mutex、futex、原子变量等同步。驱动层处理设备 DMA 时，应使用内核 DMA API，而不是自行用 `volatile` 或猜测 cache 操作。

## 8. 常见出现一致性问题的场景

| 场景 | 访问者 | 常见问题 | 优先做法 |
| --- | --- | --- | --- |
| LCD / SPI 发送 | CPU + SPI DMA | LCD 读到旧帧 | 发送前 clean |
| UART / 网卡 / 摄像头接收 | DMA + CPU | CPU 读到旧包或旧帧 | 接收前后按平台规则同步，完成后 invalidate |
| 音频双缓冲 | CPU + I2S DMA | 爆音、重复采样、数据撕裂 | buffer 所有权 + Cache 同步 |
| 多核共享 RAM | CPU0 + CPU1 | 数据和标志的可见性/顺序错误 | 原子/锁；按硬件能力处理 Cache |
| GPU / 显示控制器 | CPU + 图形/显示 DMA | 显示旧帧、撕裂 | 图形栈的 buffer 同步和 Cache API |
| MMIO 外设寄存器 | CPU + 硬件 | 读写被编译器优化或乱序 | 正确的 Device memory 映射和寄存器 API |
| Flash / XIP 代码 | CPU + Flash 控制器 | 取到旧指令或擦写时取指失败 | 遵循 SDK 的 I-Cache/Flash 操作流程 |
| PSRAM / 外部 RAM | CPU + DMA | 可访问性、Cache 与 DMA 属性不匹配 | 确认 DMA-capable 内存和 SDK 限制 |

### 8.1 MMIO 不是普通 D-Cache 问题

硬件寄存器地址应被映射为 Device/Strongly-ordered 等非普通内存属性，通常不可缓存并具备特定访问顺序。寄存器定义中的 `volatile` 主要约束编译器访问，不负责把普通 RAM 的 Cache 写回。

因此下面两件事不能混为一谈：

```c
/* 外设寄存器：通常需要 volatile，由硬件内存属性保证不可缓存。 */
volatile uint32_t *status = (volatile uint32_t *)REG_ADDR;

/* DMA 缓冲区：是否需要 clean/invalidate，取决于它是否为可缓存 RAM。 */
uint8_t dma_buffer[256];
```

## 9. 实际排查步骤

1. **确认访问者。** 谁在读写：CPU、DMA、另一 CPU 核、显示控制器还是外设？
2. **确认内存属性。** 缓冲区在内部 SRAM、PSRAM、DDR、Flash 还是不可缓存区？该区域是否允许 DMA？
3. **确认方向和所有权。** 是 CPU 写/DMA 读，还是 DMA 写/CPU 读？DMA 运行期间谁可以修改 buffer？
4. **检查 SDK 推荐接口。** 优先用 BSP/驱动提供的 DMA 映射、同步或专用内存分配接口。
5. **检查 Cache 维护范围。** 地址和长度是否覆盖整个 buffer，并满足缓存行对齐要求？
6. **检查时序。** Cache 操作是否在启动 DMA 前或完成 DMA 后执行？是否需要屏障？
7. **缩小验证。** 临时改用不可缓存 DMA 内存、关闭 D-Cache（仅用于验证）、单缓冲或加校验，判断是否真为一致性问题。

常见现象：

- LCD 偶发显示上一帧、局部花屏。
- UART/网卡收包内容像上一包，或头部正确而中间错误。
- 摄像头帧随机重复、图像局部陈旧。
- 只在开启 D-Cache、提高优化等级或切换到 PSRAM 后复现。
- 添加日志、断点或延时后问题“消失”。

## 10. 高频易错点

| 错误说法 | 更准确的说法 |
| --- | --- |
| `volatile` 能解决 DMA 缓存问题 | 不能；它不做 D-Cache clean/invalidate |
| 加一个 `DSB` 就能让 DMA 读到新数据 | 屏障只约束顺序；脏 Cache 数据仍需要 clean |
| DMA 接收完成后再 invalidate 就够了 | 若接收区可能有脏 Cache line，交给 DMA 前也要按平台规则处理 |
| 所有多核都要手动 flush Cache | 是否硬件一致取决于 SoC；但同步与内存顺序始终需要设计 |
| Cache API 可以对任意地址长度直接调用 | Cache line 粒度可能影响邻接数据，需对齐并遵循 API 约束 |
| DMA 可以访问所有 RAM | 很多芯片限制 DMA 可访问的内存区域、对齐和地址范围 |
| MMIO 只加 `volatile` 就万事大吉 | 还需要正确的 Device memory 属性、驱动 API 和必要的访问顺序 |
| DMA 完成中断就代表 CPU 能安全立刻改 buffer | 还要完成所有权切换、Cache 同步和上层并发保护 |

## 11. 面试常见问法和直白回答

### 11.1 `volatile`、Cache 一致性和 DMA 有什么关系

> `volatile` 解决的是编译器可能缓存或优化掉变量访问的问题，不解决原子性和 D-Cache 同步。DMA 直接访问 RAM，通常不经过 CPU D-Cache，所以在可缓存内存上会和 CPU 产生数据副本不一致。CPU 写、DMA 读时要在启动 DMA 前 clean；DMA 写、CPU 读时要在 DMA 完成后 invalidate。接收缓冲区在交给 DMA 前是否还需要 clean/invalidate，要按缓存行和平台 DMA API 的所有权规则处理。

### 11.2 Clean 和 Invalidate 的区别

> Clean 是把 Cache 中修改过的脏数据写回 RAM，适合让 DMA 读到 CPU 刚写的数据；Invalidate 是丢弃 Cache 副本，适合让 CPU 在 DMA 写 RAM 后重新读取新数据。Invalidate 前若该缓存行有 CPU 未写回的脏数据，可能造成数据丢失，所以要遵循交接顺序。

### 11.3 内存屏障能替代 Cache flush 吗

> 不能。内存屏障保证访问顺序或操作完成关系，但不会把 D-Cache 的脏数据自动写到 RAM。可缓存 DMA buffer 通常需要 Cache 维护，再按平台要求加屏障。

### 11.4 多核共享内存还要 Cache 操作吗

> 先看硬件是否 Cache coherent。硬件一致的平台通常不需要应用手动清缓存，但仍需原子操作、锁或消息队列保证数据和标志的发布顺序；非一致平台则需要结合共享内存属性和软件 Cache 维护。

## 12. 最简记忆版

- I-Cache 缓存指令，D-Cache 缓存数据；DMA 问题通常看 D-Cache。
- `volatile` 防编译器优化，不解决线程安全和 DMA Cache 一致性。
- CPU 写、DMA 读：启动 DMA 前 **clean**。
- DMA 写、CPU 读：DMA 完成后 **invalidate**。
- DMA 接收 buffer 交给 DMA 前，按平台规则处理旧/脏 Cache line。
- Cache 操作以缓存行为单位：DMA buffer 要对齐、长度要覆盖完整缓存行。
- 多核先判断硬件是否一致；无论是否一致，都要用同步原语保证内存顺序。
- 最可靠的工程做法是使用芯片 SDK/驱动提供的 DMA 内存与同步接口。
