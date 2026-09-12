# ESP32-S3 主 Flash、Cache 与 ISR 安全运行指南

## 文档定位

本文围绕 ESP32-S3 的主 Flash 映射执行、ICache/DCache、IRAM/内部 DRAM、PSRAM 与 DMA 的关系，解释主 Flash 因 NVS、OTA、LittleFS 等操作进入擦写窗口时，SPI DMA 完成中断为何可能使 LVGL 刷新链卡死，以及如何设计一条 Cache 暂停期间仍能安全运行的 ISR 回调链。

本文的学习与查阅价值在于：帮助读者判断代码或数据在 Flash 擦写期间是否可访问，并能检查、改造关键中断、DMA 和显示刷新路径，使其不依赖被暂停的 Flash Cache。

## 1. 从 Flash 执行：程序为何能存放在 Flash 中运行

ESP32-S3 的大部分固件代码与常量字符串都链接在主 Flash 中。CPU 并非每执行一条指令都直接读取 Flash，而是由 Cache 将 Flash 映射为可执行、可读取的地址空间：

```text
CPU 执行函数
  → 指令 Cache（ICache）
  → Cache 未命中时从主 Flash 取指令
  → CPU 获得下一条机器指令
```

这种“从 Flash 执行”的方式节省了有限的片上 RAM；但其前提是主 Flash 能稳定响应读取请求。相应地，Flash 中的只读常量、字符串和查找表通常需要经数据 Cache（DCache）访问。

## 2. 主 Flash 擦写为何会暂停 Cache

Flash 擦除和写入不是普通内存写操作：擦除通常按扇区进行且耗时较长，写入或擦除期间 Flash 会处于忙状态，无法保证继续响应正常读取。若 Cache 此时继续补充数据，CPU 可能读取到无效、旧的或不可用的 Flash 内容。

因此，ESP-IDF 在执行部分主 Flash 擦写操作时会进入受保护窗口，暂停依赖 Flash 的 Cache 访问。对于 ESP32-S3，必须同时看待 ICache 和 DCache；项目内 ESP-IDF 的相关实现会调用：

```c
Cache_Suspend_ICache();
Cache_Suspend_DCache();
```

实现位置见 [spi_flash_os_func_noos.c](/home/xl/XL/ESP/my32/esp-idf/components/spi_flash/spi_flash_os_func_noos.c:58)。在这段时间，ESP-IDF 要求仍会执行的关键代码只能位于 IRAM，所访问的数据只能位于内部 DRAM 或 ROM。

并非所有 Wi-Fi 或 NVS 操作都会禁用 Cache。普通 RAM 操作和 NVS 读取不一定触发此窗口；NVS 初始化、提交配置、写入或擦除 Flash，以及相关底层流程则可能进入该窗口。

## 3. 内存访问模型：ICache、DCache 与片上内存的边界

### 3.1 ICache：CPU 下一条执行什么

普通固件函数通常位于主 Flash 的指令映射区（IROM）。CPU 执行这类函数时，要经 ICache 从 Flash 获取机器指令：

```text
CPU 调用普通函数
  → ICache
  → 主 Flash 的代码区（IROM）
```

主 Flash 擦写时 ICache 被暂停。如果 ISR 跳转到 Flash 中的函数，CPU 无法继续取指，典型后果是 `Cache disabled but cached memory region accessed` 异常，或关键中断收尾不能及时完成。

`IRAM_ATTR` 的作用是将函数的**指令**放入片上指令 RAM（IRAM），从而避免 ICache 取指依赖。例如：

```c
static bool IRAM_ATTR lcd_flush_ready_callback(void *user_ctx)
```

### 3.2 DCache：函数运行时读写什么

函数本体放入 IRAM 并不意味着绝对安全。Flash 中的字符串、只读常量和查找表，以及 PSRAM 中的数据，仍依赖 DCache：

```c
void IRAM_ATTR callback(void)
{
    printf("DMA done");       // 字符串常量通常在 Flash
    table[index];             // const 表可能在 Flash
    psram_buffer[0] = 1;      // PSRAM 依赖 DCache
}
```

DCache 暂停时，这些数据访问同样不可用。因此，IRAM 函数不会自动使其字符串、常量或所访问的数据进入 RAM；必要时常量也需要使用 `DRAM_ATTR`。编译器生成的跳转表同样可能位于 Flash。

### 3.3 可用性总览

| CPU 要访问的内容 | 正常情况下主要依赖 | 主 Flash Cache 暂停时 |
| --- | --- | --- |
| Flash 中的函数代码（IROM） | ICache | 不可用 |
| Flash 中的只读常量、字符串、查找表（DROM） | DCache | 不可用 |
| PSRAM 中的数据、对象、任务栈 | DCache | 不可用 |
| IRAM 中的函数代码 | 不依赖 Flash Cache | 可用 |
| 内部 DRAM 中的全局变量、栈、DMA 缓冲 | 不依赖 Flash Cache | 可用 |
| ROM 函数 | ROM | 可用 |

```text
                           ┌──────────────┐
CPU 取指令 ───────────────→│ ICache       │──→ 主 Flash 的代码区（IROM）
                           └──────────────┘
CPU 读数据 ───────────────→│ DCache       │──→ 主 Flash 常量区（DROM）
                           │              └──→ PSRAM
                           └──────────────┘

CPU 直接执行 ─────────────→ IRAM
CPU 直接读写 ─────────────→ 内部 DRAM
```

ESP-IDF 对指令总线、数据总线、Flash 映射和 PSRAM 映射的说明见 [内存类型文档](https://docs.espressif.com/projects/esp-idf/en/v5.1.2/esp32s3/api-guides/memory-types.html)。

## 4. 为什么 SPI DMA 完成 ISR 容易暴露问题

SPI DMA 完成是硬件事件，不受主任务当前执行位置控制。DMA 完成后中断可能立即发生；若此时主 Flash 正在擦写，位于 Flash 或访问 Flash/PSRAM 数据的 ISR 回调就无法安全运行。

```text
Flash/NVS 正在写入或擦除
  → ICache 与 DCache 暂时不可用
  → SPI DMA 完成并触发 ISR
  → ISR 跳转到 Flash 中的回调，或访问 Flash 常量、PSRAM 数据
  → ISR 无法完成 SPI 事务收尾
  → SPI 总线或 LVGL 绘图缓冲持续处于“忙”状态
  → 后续刷新永久等待，表现为启动卡死
```

ISR 不能像普通任务一样等到 Cache 恢复后再继续；它负责硬件事件的及时收尾。若 DMA 完成状态没有向上层传播，资源就可能无法释放。严格来说，Cache 访问违规常见结果是 panic；也可能因非 IRAM 安全中断延后或关键状态未清除，最终呈现为“卡死”。

## 5. 本项目的显示完成链与处理方式

本项目中，显示 DMA 的完成通知链为：

```text
SPI DMA 完成 ISR
  → lcd_color_trans_done_callback()
  → lcd_flush_ready_callback()
  → lv_disp_flush_ready()
  → 清除 LVGL draw buffer 的 flushing 标记
```

其中前两个回调均使用 `IRAM_ATTR`，分别位于 [lcd.c](/home/xl/XL/ESP/my32/components/drivers/display/ili9341/lcd.c:33) 和 [lv_port_disp.c](/home/xl/XL/ESP/my32/components/adapters/lvgl_port/lv_port_disp.c:203)。`lv_disp_flush_ready()` 通过 [lv_conf.h](/home/xl/XL/ESP/my32/components/adapters/lvgl_port/lv_conf.h:336) 中的 `LV_ATTRIBUTE_FLUSH_READY IRAM_ATTR` 放入 IRAM。

为保证该链在 Cache 暂停窗口内完整可运行，项目采用以下约束：

- SPI 主机 ISR 启用 IRAM 配置：[`CONFIG_SPI_MASTER_ISR_IN_IRAM=y`](/home/xl/XL/ESP/my32/sdkconfig:538)。
- LCD DMA 完成回调、LVGL 完成回调和 `lv_disp_flush_ready()` 均位于 IRAM。
- ISR 仅进行 `xSemaphoreGiveFromISR()`、状态更新和通知 LVGL 等短小、不阻塞的工作。
- `s_color_trans_done_callback` 与 `s_pending_disp_drv` 为内部 DRAM 中的静态全局状态。
- 显示 DMA 缓冲使用 `MALLOC_CAP_DMA | MALLOC_CAP_8BIT` 分配在内部 DMA 内存，而非 PSRAM，见 [lv_port_disp.c](/home/xl/XL/ESP/my32/components/adapters/lvgl_port/lv_port_disp.c:100)。

DMA 是外设直接搬运内存的硬件机制，而不是一种内存。ESP-IDF 规定具有 DMA 能力的内存应通过 `MALLOC_CAP_DMA` 分配，且该能力会排除外部 PSRAM；这正是本项目显示双缓冲的分配策略。详见 [堆与内存能力文档](https://docs.espressif.com/projects/esp-idf/en/v5.1.2/esp32s3/api-reference/system/mem_alloc.html)。

## 6. ISR 安全性的正确判定标准

不能只检查 ISR 函数是否写了 `IRAM_ATTR`。安全性取决于整个调用链和全部数据访问：

```text
ISR 函数本身在 IRAM
  × 调用 Flash 中的子函数
  × 访问 Flash 中的 const 表或日志字符串
  × 访问 PSRAM 中的数据
= 仍然不安全
```

适用于主 Flash Cache 暂停窗口的设计标准为：

```text
代码与完整调用链：IRAM / ROM
读取与写入的数据：内部 DRAM
DMA 缓冲：内部、DMA-capable DRAM
禁止：Flash 代码、Flash 常量、PSRAM、普通日志、堆分配、阻塞操作
```

调用普通 `helper()` 会产生 ICache 风险；读取格式化日志字符串、`const` 表或函数指针/跳转表会产生 DCache 风险；访问 PSRAM 或调用非 ISR 安全 API 也可能失败或阻塞。ESP-IDF 也提醒，`IRAM_ATTR` 函数中的字符串和常量不一定自动移入 RAM，必要时需使用 `DRAM_ATTR`。

## 7. 主 Flash 与独立数据 Flash：以 W25Q64 为例

“Flash 是内置还是外置”并不是判断是否影响 Cache 的关键；关键在于它是否承载 CPU 的代码或数据映射，以及是否连接在主 MSPI/Flash 通道上。

本工程中的 W25Q64 是独立数据 Flash：

```text
W25Q64
  → GPIO36/35/37/38
  → 软件 SPI（GPIO + GPTimer）
  → 读写数据
```

它不是固件启动、代码执行所使用的主 Flash，也未映射为 CPU 的代码区或数据区。当前驱动经 `sim_spi_transfer()` 读写，擦写后轮询 W25Q64 的 Busy 位；相关初始化和驱动可见 [w25q64_test.c](/home/xl/XL/ESP/my32/components/diagnostics/w25q64_test/w25q64_test.c:26) 与 [w25q64.c](/home/xl/XL/ESP/my32/components/drivers/storage/w25q64/w25q64.c:107)。

W25Q64 擦写时会自行忙碌，当前任务需要等待它完成，但通常不会使 ESP-IDF 暂停主 ICache/DCache，也不会直接导致本次 LVGL SPI 回调链卡死。

若另一颗物理上外置的 Flash 接在 ESP32-S3 主 MSPI/Flash 通道，并被映射为 XIP 代码或数据，或通过 ESP-IDF 的 `esp_flash` 机制执行受保护擦写，则仍可能涉及 Cache 暂停。物理位置不等同于系统角色：ESP32-S3 的主 Flash 通常本身也是芯片外或模组内的 SPI Flash，却承担固件存储和映射执行职责。

| 类别 | 本项目例子 | 能否运行代码 | 擦写时与 Cache 的关系 |
| --- | --- | --- | --- |
| 主 Flash | ESP-IDF 固件、NVS、OTA、LittleFS 分区 | 可以，固件通常从这里执行 | 擦写时可能暂停 ICache 与 DCache |
| 独立数据 Flash | W25Q64 | 当前不能 | 自身忙碌，不会天然导致主 Cache 暂停 |

```text
软件 SPI ─────────────────→ W25Q64（独立外设，不参与主 Flash 映射）
```

## 8. 概念速查与排查要点

| 概念 | 含义与主要用途 | 主 Flash Cache 暂停时 |
| --- | --- | --- |
| Flash | 非易失存储，用于固件、NVS、OTA、LittleFS 与常量 | 主 Flash 的映射访问不可依赖 |
| ICache | 缓存从主 Flash 读取的机器指令 | 不能从 IROM 继续取指 |
| DCache | 缓存 Flash 常量、PSRAM 等数据 | 不能访问 DROM、PSRAM |
| Flash Cache | ICache 与 DCache 的统称，用于主 Flash 映射 | 擦写窗口会暂停或失效 |
| IROM | 映射到指令地址空间的 Flash 代码，普通函数通常在此 | 不安全 |
| DROM | 映射到数据地址空间的 Flash 只读数据，如字符串、`const` 表、图片常量 | 不安全 |
| IRAM | 芯片内部指令 RAM，用于 `IRAM_ATTR` 函数和关键 ISR | 安全 |
| 内部 DRAM | 芯片内部数据 RAM，用于全局变量、任务栈、普通堆与 DMA 数据 | 安全 |
| D/IRAM | 可分配给指令或数据用途的片上 SRAM | 取决于实际分配方式 |
| PSRAM | 芯片外扩展 RAM，常用于大对象、图片解码和 LVGL 普通堆 | 不安全，依赖 DCache |
| DMA | 外设直接搬运内存的硬件机制 | 缓冲需位于内部 DMA-capable DRAM |

排查 Flash 擦写期间的中断、DMA 或显示异常时，按以下顺序检查：

1. 确认操作对象是否为承载映射代码/数据的主 Flash，而非独立数据 Flash。
2. 检查 ISR 及其所有被调用函数是否均在 IRAM 或 ROM。
3. 检查 ISR 访问的全局状态、字符串、`const` 表、函数指针和跳转表，确认不依赖 Flash 或 PSRAM。
4. 检查 DMA 缓冲是否使用内部 `MALLOC_CAP_DMA` 内存。
5. 确认 ISR 中没有日志、堆分配、阻塞操作或非 ISR 安全 API。
6. 沿着“硬件完成 → ISR → 上层完成通知 → 资源释放”追踪，确认每一环在 Cache 暂停时都能执行。

## 9. 核心结论

可以把主 Flash 看作同时存放程序和资料的远端仓库，ICache 与 DCache 是两条取用通道，IRAM 与内部 DRAM 是手边的应急工作台。主 Flash 擦写时，两条 Cache 通道会暂停；若 ISR 仍要经这些通道获取指令或数据，DMA 的完成手续就可能无法办结，进而阻塞 SPI 与 LVGL 刷新。

处理此类问题的关键不是孤立地给 ISR 加上 `IRAM_ATTR`，而是审查并约束**整条 ISR 回调链**：代码只依赖 IRAM/ROM，数据只依赖内部 DRAM，DMA 缓冲位于内部 DMA-capable DRAM，并避免 Flash 常量、PSRAM、日志、堆分配和阻塞调用。
