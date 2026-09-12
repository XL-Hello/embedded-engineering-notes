# 一次 Flash 擦写，为什么会让 DMA、LVGL 和 ISR 全部卡死？

> 目标：本文结合 ESP32-S3 的主 Flash 映射执行、ICache/DCache、IRAM/内部 DRAM、PSRAM、DMA 与 LVGL 刷新链路，解释主 Flash 擦写期间为何可能出现 DMA 收尾失败、显示刷新卡死或 Cache 访问异常，并给出可复用的设计与排查方法。
>
> 核心结论：`volatile` 解决编译器访问优化，锁和原子操作解决并发同步，Cache clean/invalidate 解决 CPU Cache 与 RAM 的数据副本同步。主 Flash Cache 暂停期间，必须保证关键 ISR 的**完整调用链**只依赖 IRAM/ROM 和内部 DRAM。
>
> 说明：具体 Cache API、PSRAM DMA 能力、Flash 擦写并发规则及内存属性应以所用 ESP-IDF 版本、芯片手册和驱动文档为准。

## 1. 从一个“显示卡死”现象理解问题

设想一个典型场景：LVGL 使用 SPI DMA 将像素发送给 LCD；同时系统正在执行 NVS 提交、OTA、LittleFS 更新或其他主 Flash 擦写操作。

```text
主 Flash 正在擦写
    -> ICache 与 DCache 暂时不可用
    -> SPI DMA 恰好完成并触发中断
    -> ISR 跳转到 Flash 中的函数，或访问 Flash 常量 / PSRAM 数据
    -> DMA 完成手续无法正常收尾
    -> SPI 事务或 LVGL buffer 一直保持 busy / flushing
    -> 后续显示刷新永久等待，表现为花屏、卡住或启动异常
```

严格来说，Cache 访问违规常见结果是 panic，例如 `Cache disabled but cached memory region accessed`；也可能由于非 IRAM-safe 中断被延后、DMA 状态未清除或上层未收到完成通知，最终表现为“系统卡死”。

问题的关键并不是“DMA 有问题”，而是：**Flash Cache 暂停窗口内，仍必须执行的中断和 DMA 完成链是否还能取得指令与数据。**

## 2. 先区分四类问题

嵌入式中的“数据不对”常被统称为 Cache 问题，但实际上可能来自不同层面：

| 机制 | 主要解决什么 | 不能替代什么 |
| --- | --- | --- |
| `volatile` | 防止编译器省略、合并或长期缓存变量访问 | 原子性、互斥、D-Cache 同步 |
| 原子操作、锁、队列、信号量 | 多任务、多核或 ISR 与任务间的并发同步 | DMA 与 Cache 数据同步 |
| 内存屏障 | 约束 CPU/编译器对内存访问的顺序 | 将脏 Cache 数据写回 RAM |
| Cache clean/invalidate | 同步 CPU Cache 与 RAM 中的数据副本 | 线程安全与 buffer 所有权协议 |
| DMA | 让外设直接读写内存，减少 CPU 搬运 | 自动维护 CPU D-Cache（通常不会） |

直白地说：

> `volatile` 管“编译器别自作主张”；锁和原子操作管“大家别同时乱改”；Cache 维护管“CPU Cache 和 RAM 别各保留一份不同的数据”。

## 3. ESP32-S3 的内存与 Cache 访问模型

ESP32-S3 的大部分程序代码与只读常量位于主 SPI Flash 中。CPU 并不是每执行一条指令都直接读取 Flash，而是通过 MMU 和 Cache 将 Flash 映射进可执行、可读取的地址空间。

```text
CPU 取指： IROM 代码  <- I-Cache <- MMU <- 主 Flash
CPU 读数： DROM 常量  <- D-Cache <- MMU <- 主 Flash
           PSRAM 数据 <- D-Cache <- MMU <- 外部 PSRAM

CPU 直接执行：IRAM（内部指令 RAM）
CPU 直接读写：内部 DRAM
```

| 区域 | 典型内容 | 正常访问路径 | 主 Flash Cache 暂停时 |
| --- | --- | --- | --- |
| `IROM` | 普通应用函数 | 主 Flash -> ICache -> CPU | 不可安全执行 |
| `DROM` | 字符串、`const` 表、只读资源 | 主 Flash -> DCache -> CPU | 不可安全访问 |
| `IRAM` | 关键代码、IRAM-safe ISR | 内部 SRAM | 可用 |
| 内部 `DRAM` | 全局状态、任务栈、内部 DMA buffer | 内部 SRAM | 可用 |
| `PSRAM` | 大对象、大帧缓冲、扩展堆 | 外部 RAM -> DCache -> CPU | 通常不可访问 |
| ROM | 芯片固化函数 | ROM | 可用 |

这里要注意：`IRAM` 与 `DRAM` 是片内 SRAM 的不同用途或总线视图；`IROM` 与 `DROM` 则通常是主 Flash 映射得到的代码与只读数据区域。不能因为名字中都有 RAM 或 ROM，就把它们当成相同的物理存储。

## 4. 主 Flash 擦写为什么会暂停 Cache

Flash 擦除与写入不是普通内存写操作。擦除通常以扇区为单位且耗时较长，写入或擦除期间 Flash 处于忙状态，不能保证继续响应正常读取。

若 Cache 在这时继续尝试从 Flash 补充指令或数据，CPU 可能取到无效、旧的或不可用的内容。因此，ESP-IDF 在部分主 Flash 擦写操作中会进入受保护窗口，暂停依赖主 Flash 的 Cache 访问。

```text
普通函数执行
    -> ICache 命中：继续运行
    -> ICache 未命中：需从主 Flash 取指

主 Flash 正在擦写
    -> Flash 无法可靠响应读取
    -> ICache / DCache 映射访问不可依赖
    -> IROM、DROM 与通常依赖 DCache 的 PSRAM 均不能作为关键路径依赖
```

并非每次 Wi-Fi、NVS 或文件系统调用都会触发 Cache 暂停。普通 RAM 操作和 NVS 读取未必进入该窗口；但 NVS 初始化、提交、写入、擦除，OTA 和文件系统底层擦写等流程都可能触发，工程上不应假设它“不会刚好发生”。

## 5. `IRAM_ATTR` 为什么还不够

`IRAM_ATTR` 的作用是将函数的**指令**放进 IRAM，使它不再依赖 ICache 从 Flash 取指。

```c
static bool IRAM_ATTR lcd_flush_ready_callback(void *user_ctx)
{
    /* 代码本体位于 IRAM。 */
    return false;
}
```

但函数本体在 IRAM，不代表所有依赖都安全：

```c
void IRAM_ATTR callback(void)
{
    printf("DMA done");       // 字符串和日志路径可能依赖 Flash
    use_table(table[index]);   // const 表可能位于 DROM
    psram_buffer[0] = 1;       // PSRAM 通常依赖 DCache
}
```

因此，对需要穿越 Flash Cache 暂停窗口的 ISR，正确判定标准是：

```text
ISR 函数在 IRAM
    + 所有被调用函数在 IRAM 或 ROM
    + 所有读写状态位于内部 DRAM
    + DMA buffer 位于内部 DMA-capable 内存
    + 不访问 Flash 常量、PSRAM，不记录普通日志，不分配堆，不阻塞
    = IRAM-safe ISR 链路
```

还应检查以下容易遗漏的依赖：

- 普通辅助函数是否实际链接在 IROM。
- 格式化日志字符串、`const` 查找表、图片资源是否位于 DROM。
- 函数指针、C++ 虚函数表、编译器生成的跳转表是否间接落在 Flash。
- ISR 调用的 RTOS API 是否提供 `FromISR` 版本。
- 回调指针、状态变量、队列控制块是否位于内部 DRAM。

必要时，Flash 常量可使用 `DRAM_ATTR` 放入内部 DRAM：

```c
static const char isr_tag[] DRAM_ATTR = "lcd";
```

## 6. SPI DMA、LVGL 与 ISR 完成链

以 SPI LCD 为例，DMA 完成后的通知链通常类似：

```text
SPI DMA 完成 ISR
    -> LCD color-transfer-done callback
    -> LVGL flush-ready callback
    -> lv_disp_flush_ready()
    -> 清除 draw buffer 的 flushing 标记
    -> LVGL 可以提交下一帧
```

这条链中只要有一环在 Flash Cache 暂停时跳到 IROM、访问 DROM 或访问 PSRAM，DMA 完成状态就可能无法及时上报，导致刷新链停滞。

设计原则：

- SPI 主机中断应按 ESP-IDF 的 IRAM ISR 配置启用。
- DMA 完成回调、LVGL 完成回调及必要的 `flush_ready` 路径均应位于 IRAM。
- ISR 中仅执行短小的状态更新、任务通知、`xSemaphoreGiveFromISR()` 等 ISR-safe 操作。
- 回调状态、pending 指针等关键全局数据应位于内部 DRAM。
- ISR 中禁止普通日志、堆分配、等待锁、延时和阻塞调用。

## 7. DMA 与 D-Cache 一致性

DMA 直接访问 RAM，通常不经过 CPU D-Cache。对于可缓存内存，CPU Cache 与 RAM 因而可能各有一份不同的数据。

### 7.1 CPU 写、DMA 读：发送前 Clean

以 SPI/LCD 发送帧缓冲为例：

```text
CPU 绘制新图像
    -> 新像素可能只停留在 D-Cache
    -> Clean：将脏 Cache 数据写回 RAM
    -> 启动 DMA
    -> DMA 从 RAM 读取最新像素并发送
```

```c
fill_tx_buffer(tx_buf, len);
cache_clean(tx_buf, len);      /* 平台相关 API */
memory_barrier_if_required();
dma_start_tx(tx_buf, len);
```

DMA 未完成前，CPU 不能修改该发送 buffer；否则 DMA 可能读到前后混合的数据。应通过双缓冲、队列或清晰的所有权协议解决。

### 7.2 DMA 写、CPU 读：完成后 Invalidate

以 UART、网卡或摄像头接收为例：

```text
DMA 写 RAM
    -> CPU D-Cache 可能仍保存旧数据
    -> DMA 完成后 Invalidate
    -> CPU 下次读取时从 RAM 获得新数据
```

```c
cache_invalidate(rx_buf, received_len);
process_rx_buffer(rx_buf, received_len);
```

接收 buffer 交给 DMA 前，若其 Cache line 可能是脏的，还需要按平台 DMA API 的所有权规则 clean + invalidate，避免 CPU 后续写回旧数据覆盖 DMA 已写入的新内容。

通用原则是：

> 交给 DMA 前，CPU 不应保留脏副本；DMA 归还 CPU 后，CPU 不应继续使用旧副本。

### 7.3 内存屏障不能替代 Cache 维护

内存屏障只约束访问顺序或完成关系，不会把 D-Cache 中的脏数据自动写入 RAM。

```text
CPU 写 buffer -> D-Cache 中有新数据
    -> 仅执行 DSB / memory barrier
    -> RAM 仍可能是旧数据
    -> DMA 仍可能读到旧内容
```

对于可缓存 DMA buffer，通常应先 Cache clean/invalidate，再按平台要求使用屏障。

## 8. DMA buffer、PSRAM 与对齐

DMA 是外设直接搬运内存的机制，不代表所有 RAM 都可直接作为 DMA buffer。ESP-IDF 工程中应优先使用内存能力分配接口和驱动提供的同步路径：

```c
void *buf = heap_caps_malloc(size,
                             MALLOC_CAP_DMA | MALLOC_CAP_8BIT);
```

工程建议：

- SPI DMA 描述符、时序关键的小 buffer、Cache 暂停期间使用的数据放内部 RAM。
- 显示 DMA buffer 优先使用内部 `MALLOC_CAP_DMA` 内存。
- 大帧缓冲可考虑 PSRAM，但要确认所用 ESP-IDF 版本和具体外设驱动对 PSRAM DMA、bounce buffer、对齐和同步的支持。
- DMA 描述符通常不应放在 PSRAM。
- 主 Flash 擦写期间，关键 ISR 路径不要访问 PSRAM。
- 不要以为 `volatile` 能解决旧帧、花屏或撕裂。

Cache 操作通常以 **Cache line** 为最小单位。若 DMA buffer 起止地址未对齐，clean 或 invalidate 可能连带影响相邻变量：

```text
| 相邻变量 |      DMA buffer      | 相邻变量 |
^                         ^
Cache line 边界不对齐时，维护范围可能覆盖相邻数据
```

建议 DMA buffer 按 Cache line 对齐，长度向 Cache line 大小取整，不与频繁修改的普通变量共享同一 Cache line，并优先使用 SDK 的 DMA 分配、映射和同步接口。

## 9. `volatile` 的正确定位

`volatile` 告诉编译器：该对象可能被当前代码不可见的主体改变，每次访问都应生成实际读写操作。

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
}
```

适用场景：

- MMIO 外设寄存器。
- 被中断、硬件或调试器异步改变的简单状态。
- 简单轮询标志。

但 `volatile` 不保证：

- `count++` 等复合操作的原子性。
- 多任务、多核间的互斥与线程安全。
- 数据和 ready 标志的发布顺序。
- CPU 与 DMA 的 D-Cache 一致性。

ISR 与任务通信优先使用 ISR-safe 队列、信号量、任务通知或原子操作；多核共享数据应使用锁、消息队列或 acquire/release 语义建立可靠的发布顺序。

## 10. 主 Flash 与独立数据 Flash

“Flash 是不是外置”不是判断是否影响 Cache 的关键。关键在于它是否承载 CPU 的映射代码或数据，以及是否接在主 MSPI/Flash 通道上。

| 类别 | 典型用途 | 擦写时与 Cache 的关系 |
| --- | --- | --- |
| 主 Flash | 固件、NVS、OTA、LittleFS、映射常量 | 可能暂停 ICache / DCache |
| 独立数据 Flash | 通过普通 SPI/QSPI 驱动访问的数据存储 | 自身忙碌，但通常不暂停主 Flash Cache |

例如一颗经 GPIO 软件 SPI 访问的 W25Q64，只是独立外设：擦写期间当前任务需要轮询其 Busy 状态，却不会天然导致 ESP32-S3 主 Flash Cache 暂停。反之，物理上位于芯片外的 Flash 若承载 XIP 或主 Flash 映射角色，仍须按主 Flash 的规则处理。

## 11. 常见错误说法

| 错误说法 | 更准确的说法 |
| --- | --- |
| `volatile` 能解决 DMA 缓存问题 | 不能；它不执行 D-Cache clean/invalidate |
| 给 ISR 加 `IRAM_ATTR` 就绝对安全 | 还要保证完整调用链和全部数据不依赖 Flash/PSRAM |
| 加一个内存屏障，DMA 就能读到新数据 | 屏障不负责将脏 Cache 写回 RAM，仍可能需要 clean |
| DMA 接收完成后 invalidate 就够了 | 接收前也要按平台规则处理旧/脏 Cache line |
| DMA 可以访问所有 RAM | DMA 可访问区域、地址范围和对齐受芯片及驱动限制 |
| PSRAM 和内部 DRAM 对 ISR 一样安全 | 主 Flash Cache 暂停时，PSRAM 通常不可作为关键路径依赖 |
| 所有 Flash 擦写都会导致显示异常 | 只有关键中断链依赖被暂停的 Cache 路径时才会出问题 |

## 12. 排查清单

当出现 Flash 擦写期间的花屏、旧数据、DMA 卡住、显示刷新停滞或 Cache 异常时，按以下顺序检查：

1. 确认操作对象是主 Flash，还是独立数据 Flash。
2. 检查 ISR、回调及完整调用链是否均位于 IRAM 或 ROM。
3. 检查 ISR 是否访问 Flash 字符串、`const` 表、跳转表、函数指针或 PSRAM。
4. 检查 DMA buffer 是否位于正确的内部 DMA-capable 内存。
5. 确认 DMA 传输前后是否按驱动或平台要求完成 Cache 同步。
6. 确认 DMA 运行期间 buffer 不会被 CPU、LVGL 或其他任务覆盖。
7. 确认 ISR 内没有日志、堆分配、阻塞操作或非 ISR-safe API。
8. 沿着“硬件完成 -> ISR -> 上层完成通知 -> 资源释放”逐环验证，确认每一环在 Cache 暂停窗口中都能执行。

## 13. 最简记忆版

- I-Cache 缓存指令，D-Cache 缓存数据；DMA 一致性问题通常先看 D-Cache。
- 主 Flash 擦写期间，普通 IROM 代码、DROM 常量和 PSRAM 可能不可用。
- `IRAM_ATTR` 只保证函数指令在 IRAM；完整调用链和数据也必须安全。
- CPU 写、DMA 读：启动 DMA 前 **clean**。
- DMA 写、CPU 读：DMA 完成后 **invalidate**；接收 buffer 交给 DMA 前也要按平台规则处理。
- `volatile` 防编译器优化，不解决 DMA Cache 一致性、原子性或线程安全。
- 关键 ISR 与 DMA 收尾路径应使用 IRAM、内部 DRAM 与 DMA-capable buffer，避免 Flash、PSRAM、日志和阻塞操作。
