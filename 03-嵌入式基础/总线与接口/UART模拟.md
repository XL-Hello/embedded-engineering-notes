# ESP32-S3 UART实现入门

本文分为两部分：先认识 ESP32-S3 的硬件 UART 资源和引脚规则，再以“GPIO + 定时器”软件 UART 为例学习 UART 帧格式、收发时序和驱动结构。软件 UART 是理解协议底层机制的学习内容，不是 ESP32-S3 提供的额外硬件串口。

> 结论先行：ESP32-S3 有 **UART0、UART1、UART2 共 3 路硬件 UART 控制器**。它们具备硬件状态机和 FIFO；软件 UART 是使用 GPIO、定时器和 CPU 模拟出的另一种实现方式。

## 1. ESP32-S3 的硬件 UART 资源

### 1.1 控制器数量与能力

ESP32-S3 的三路 UART 控制器寄存器组相同，可独立同时工作。每路均支持 TTL 电平异步串口、硬件 FIFO、中断、可选 CTS/RTS 硬件流控，以及 RS485 相关模式。

| 项目 | ESP32-S3 UART 能力 |
| --- | --- |
| 控制器 | UART0、UART1、UART2，共 3 路 |
| 硬件 FIFO | 每路 UART 的硬件 FIFO 长度为 **128 字节** |
| 最高可配置波特率 | 5 Mbps |
| 帧格式 | 5/6/7/8 数据位；1/1.5/2 停止位；无/奇/偶校验 |
| 流控与模式 | CTS/RTS 硬件流控；RS485 模式；可配置唤醒和多种中断 |
| 典型中断/事件 | 接收数据、RX FIFO 满/溢出、TX FIFO 空、帧错误、校验错误、break、模式检测等 |

**硬件 FIFO 与驱动软件缓冲区不能混为一谈。** ESP-IDF 的 `uart_driver_install()` 参数中的 `rx_buffer_size`、`tx_buffer_size` 是驱动在 RAM 中创建的 Ring Buffer 大小，不是芯片 FIFO 容量。例如传入 1024 和 256，表示驱动软件缓冲区的配置；并不代表硬件具有 1024 字节 RX FIFO 与 256 字节 TX FIFO。

### 1.2 引脚映射：灵活但不是毫无限制

UART 信号可通过 GPIO Matrix 映射到合适的 GPIO；使用 ESP-IDF 的 `uart_set_pin()` 即可配置 TX、RX、RTS、CTS。若某信号刚好使用该 GPIO 的直连 IOMUX 功能，则可走 IOMUX；否则走 GPIO Matrix。

“任意 GPIO 都能使用”应理解为：**在满足 GPIO 自身能力、板级占用和启动约束的前提下，UART 信号可灵活重映射到空闲 GPIO**。实际选脚时还要避开：

- 输入专用 GPIO 不可承担 TX、RTS 等输出信号。
- Flash/PSRAM、USB、板载外设、下载电路和已分配外设所占用的 GPIO。
- 启动配置（strapping）相关 GPIO，避免外部电路影响上电启动。
- 同一 GPIO 同时被多个互相冲突的外设输出驱动的情况。

三路 UART 控制器本身不互相抢占；UART 与 SPI、I2S、LCD 等外设通常是 **GPIO 资源** 发生冲突，而不是控制器发生冲突。

### 1.3 UART0、下载与 USB 串口的关系

芯片的 U0TXD/U0RXD 默认引脚分别是 GPIO43/GPIO44；UART0 常用于 UART 下载与日志。开发阶段通常保留这一路，业务外设优先考虑 UART1、UART2。

但“应用中改了 UART0 引脚，就一定无法下载”并不严谨：UART 下载依赖的是 ROM 下载路径和板级连接，UART0 仍可作为下载通道；应用运行后重映射 UART0 会影响该应用的日志或业务通信。ESP32-S3 还可通过其 USB Serial/JTAG 或 USB 外设进行下载与控制台通信，具体取决于硬件连接和 ESP-IDF 配置。

**USB CDC/USB Serial-JTAG 不等于 UART。** 它们属于 USB 相关外设，不占用 UART0/1/2 控制器；但会占用相应 USB 引脚和板级 USB 资源。

### 1.4 常规资源分配建议

| 资源 | 常见分工 |
| --- | --- |
| UART0 | 调试日志或 UART 下载通道 |
| UART1 | GPS、传感器、扫码设备等业务模块 |
| UART2 | 另一条业务链路，例如屏幕串口或 Modbus/RS485 |
| USB Serial/JTAG 或 USB CDC | 可选的下载、控制台或 USB 通信，不消耗 UART 控制器 |
| 软件 UART | 学习 UART 位时序；仅在硬件 UART 不足且速率、CPU 占用允许时考虑 |

若确实需要超过 3 路 UART，可采用“3 路硬件 UART + 软件 UART”的组合。软件 UART 会消耗 CPU 和定时器资源，且抗中断抖动能力较差；不适合高波特率或持续大吞吐数据。

### 1.5 ESP-IDF：UART1 引脚重映射示例

```c
#include "driver/uart.h"

uart_config_t uart_cfg = {
    .baud_rate = 115200,
    .data_bits = UART_DATA_8_BITS,
    .parity    = UART_PARITY_DISABLE,
    .stop_bits = UART_STOP_BITS_1,
    .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
};

ESP_ERROR_CHECK(uart_param_config(UART_NUM_1, &uart_cfg));
ESP_ERROR_CHECK(uart_set_pin(UART_NUM_1,
                             GPIO_NUM_17,  // TX
                             GPIO_NUM_18,  // RX
                             UART_PIN_NO_CHANGE,
                             UART_PIN_NO_CHANGE));
ESP_ERROR_CHECK(uart_driver_install(UART_NUM_1,
                                    1024,   // RX 软件 Ring Buffer 大小
                                    256,    // TX 软件 Ring Buffer 大小
                                    0, NULL, 0));
```

选择 GPIO17/GPIO18 仅是示例。实际工程应先核对芯片封装、开发板原理图和已占用 GPIO，不能把“GPIO Matrix 可重映射”理解为无需资源检查。

### 1.6 本节资料依据

- [ESP-IDF：ESP32-S3 UART 驱动](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/uart.html)
- [ESP-IDF：ESP32-S3 SoC 能力宏](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/system/soc_caps.html)
- [乐鑫硬件设计指南：ESP32-S3 UART 与默认引脚](https://docs.espressif.com/projects/esp-hardware-design-guidelines/zh_CN/latest/esp32s3/esp-hardware-design-guidelines-zh_CN-master-esp32s3.pdf)

## 2. UART 是什么

UART（Universal Asynchronous Receiver/Transmitter，通用异步收发器）是一种按位串行通信方式。

- **串行**：一个引脚按时间顺序逐位发送数据。
- **异步**：发送端和接收端不共享时钟线；双方预先约定波特率、数据位、校验位和停止位。
- **全双工**：通常用独立的 TX 和 RX 两根数据线，因而可同时发送和接收。

UART 的电气空闲状态通常是高电平。接收端看到高到低的跳变，就认为可能有一个新字符开始，并据此建立本字符的采样时间基准。

## 3. 一帧数据：以 8N1 为例

最常见的 UART 格式是 **8N1**：8 个数据位（8）、无校验位（N）、1 个停止位（1）。一帧如下：

```text
空闲       起始位         数据位（低位先发）              停止位    空闲
 高  ────    低    ─── D0 D1 D2 D3 D4 D5 D6 D7 ───  高  ─── 高
              1 bit              每位各 1 bit              1 bit
```

因此，一个字节在线路上实际占用 10 个 bit：

```text
1 个起始位 + 8 个数据位 + 1 个停止位 = 10 bit
```

数据位按 **LSB first（低位先发）** 传输。若发送 `0x53`（二进制 `0101 0011`），在线路上依次出现的有效数据位是 `D0` 到 `D7`，即 `1、1、0、0、1、0、1、0`。

停止位为高电平，既标志本帧结束，也为下一帧可能出现的低电平起始位提供清晰边沿。若接收端在停止位采样点读到低电平，应视为帧格式错误（framing error）。

## 4. 波特率、位宽与误差

**波特率（baud）** 在这里可近似理解为每秒传输的 bit 数。一个 bit 的时间为：

```text
Tbit = 1 / baud
```

以 9600 baud 为例：

```text
Tbit = 1 / 9600 s ≈ 104.1667 μs
```

8N1 每字节需要 10 bit，因此理论有效负载上限约为：

```text
9600 / 10 = 960 byte/s
```

软件驱动一般使用定时器产生 bit 周期。若定时器分辨率为 1 MHz，则计数单位为 1 μs，只能配置整数微秒周期。可先把半位宽取整，再由两个半位构成整位：

```c
#define UART_HALF_BIT_US \
    ((TIMER_RESOLUTION_HZ + UART_BAUDRATE) / (2UL * UART_BAUDRATE))
#define UART_BIT_US      (2UL * UART_HALF_BIT_US)
```

例如 9600 baud 时可得到 `52 μs` 的半位宽和 `104 μs` 的整位宽，对应实际波特率约为 9615 baud，误差约为 0.16%。

误差的来源包括时钟源精度、定时器量化、发送端与接收端的频率偏差，以及中断响应抖动。误差会在一个字符内累计，所以波特率越高、帧越长，对时序越敏感。

## 5. 软件 UART 的总体结构

硬件 UART 会在外设内部完成起始位检测、位采样、移位、缓冲和错误检测。软件 UART 则把这些工作拆分给 GPIO、定时器和软件状态机：

```text
发送任务
   │
   ▼
发送接口 ──→ TX 状态机 ──→ TX 定时器中断 ──→ TX GPIO

RX GPIO ──→ 起始位下降沿中断 ──→ RX 定时器中断 ──→ RX 状态机
                                                           │
                                                           ▼
                                                   接收缓冲区
                                                           │
                                                           ▼
                                                       接收接口
```

TX 和 RX 的开始时刻互不相关。若要支持全双工，最直观的设计是为 TX、RX 分别提供定时器和状态机；这样接收过程不会阻塞发送过程。

## 6. 初始化应该建立什么

一个软件 UART 驱动通常在初始化中完成以下工作：

1. 配置 TX GPIO 为输出，并先输出高电平，建立空闲状态。
2. 配置 RX GPIO 为输入；空闲线路必须能稳定读到高电平，必要时使用上拉。
3. 创建 TX 定时器，周期为一个 bit，用于逐位发送。
4. 创建 RX 定时器，周期为半个 bit，用于在数据位中点采样。
5. 创建 RX 缓冲区，用于把 ISR 接收到的字节交给任务上下文处理。
6. 注册 RX GPIO 的下降沿中断；只在所有 ISR 会访问的资源就绪后才使能它。
7. 创建发送互斥锁或等价同步机制，保护共享的 TX 状态。

初始化顺序很重要：若 RX 中断先于定时器、状态变量或缓冲区就绪，起始沿到来时 ISR 可能访问未初始化资源。

## 7. TX：如何逐位发送一个字节

发送状态机可以设计为：

```text
TX_IDLE → TX_START → TX_DATA → TX_STOP → TX_IDLE
```

各状态的含义如下：

| 状态 | GPIO 输出 | 下一步 |
| --- | --- | --- |
| `TX_IDLE` | 高电平 | 等待待发字节 |
| `TX_START` | 低电平 | 数据位索引置 0 |
| `TX_DATA` | 依次输出 D0 至 D7 | 索引递增 |
| `TX_STOP` | 高电平 | 停止定时器并回到空闲 |

当前项目的 TX GPTimer 回调 `tx_timer_on_alarm_cb()` 对应以下伪代码。回调始终返回 `false`，表示没有要求 ISR 结束后立即切换任务：

```c
tx_timer_on_alarm_cb(timer) {
    if (s_tx.state == TX_START) {
        s_tx.bit = 0;
        set_gpio_level(SIM_UART_TX_PIN, LOW);   // 输出起始位
        s_tx.state = TX_DATA;
        return false;
    }

    if (s_tx.state == TX_DATA) {
        level = (s_tx.data >> s_tx.bit) & 1U;   // LSB first
        set_gpio_level(SIM_UART_TX_PIN, level);
        s_tx.bit++;

        if (s_tx.bit >= SIM_UART_DATA_BITS) {
            s_tx.state = TX_STOP;
        }
        return false;
    }

    if (s_tx.state == TX_STOP) {
        set_gpio_level(SIM_UART_TX_PIN, HIGH);  // 输出停止位/恢复空闲
        stop_timer(timer);
        s_tx.state = TX_IDLE;
    }

    return false;
}
```

任务侧 `sim_uart_send()` 与回调共享 `s_tx`。其实际流程不是“将数据交给后台后立即返回”，而是逐字节启动状态机并等待发送完成：

```c
sim_uart_send(data, len) {
    if (data == NULL || len == 0 ||
        s_tx_gptimer == NULL || s_tx_mutex == NULL) {
        return -1;
    }

    if (take_mutex(s_tx_mutex, WAIT_FOREVER) failed) {
        return -1;
    }

    result = 0;

    for (i = 0; i < len; i++) {
        s_tx.data = data[i];
        s_tx.state = TX_START;

        err = set_timer_raw_count(s_tx_gptimer, 0);
        if (err == OK) {
            err = start_timer(s_tx_gptimer);
        }

        if (err != OK) {
            s_tx.state = TX_IDLE;
            set_gpio_level(SIM_UART_TX_PIN, HIGH);
            result = -1;
            break;
        }

        while (s_tx.state != TX_IDLE) {
            taskYIELD();   // 当前实现为轮询等待，没有完成通知和超时
        }
    }

    give_mutex(s_tx_mutex);
    return result;         // 全部成功返回 0，失败返回 -1
}
```

开始发送一个字节后，每个 `SIM_UART_BIT_US` 周期由定时器回调推进一次状态。回调在 `TX_STOP` 中将线路拉高后立即把状态恢复为 `TX_IDLE`；任务观察到空闲后，才会装载下一个字节。

多个任务可能同时调用发送接口，而 TX 状态机只有一份共享状态。因此必须串行化发送请求，例如用 mutex 覆盖整个发送调用，保证两个消息的 bit 不会交叉混在同一条线路上。

## 8. RX：从下降沿到中点采样

接收状态机同样可以设计为：

```text
RX_IDLE → RX_START → RX_DATA → RX_STOP → RX_IDLE
```

### 8.1 先捕获起始位

当 RX 空闲为高时，下降沿代表起始位的候选边界。GPIO ISR 中应只做少量固定工作：

1. 确认当前状态是 `RX_IDLE`。
2. 暂时关闭 RX 下降沿中断。
3. 清零接收字节、数据位索引和半位计数。
4. 切换到 `RX_START`。
5. 清零并启动 RX 定时器。

接收期间必须关闭该下降沿中断，因为数据位本身也可能从高变低；这些跳变不是新的起始位。完整接收或判定失败后，再清除中断状态并重新使能中断。

当前项目的 GPIO ISR `sim_uart_isr_handler()` 对应以下伪代码。需要注意：当前代码调用 GPTimer 控制函数后没有检查返回值。

```c
sim_uart_isr_handler() {
    if (s_rx.state == RX_IDLE) {
        disable_gpio_interrupt(SIM_UART_RX_PIN);

        s_rx.state = RX_START;
        s_rx.bit = 0;
        s_rx.data = 0;
        s_rx.half_tick = 0;

        set_timer_raw_count(s_rx_gptimer, 0);  // 当前未检查错误
        start_timer(s_rx_gptimer);             // 当前未检查错误
    }
}
```

### 8.2 为什么采样位中心

直接在跳变边沿读电平风险很高：信号传播延迟、发送端与接收端的时钟差和噪声都会使边沿位置不稳定。每一位的中心离相邻边沿最远，采样裕量最大。

一种容易理解的实现是让 RX 定时器每 **0.5 bit** 触发一次，只在奇数个半位时采样：

| 相对起始下降沿的时间 | 动作 |
| --- | --- |
| 0.5 bit | 再读 RX；仍为低才确认是真起始位 |
| 1.5 bit | 采样 D0 |
| 2.5 bit | 采样 D1 |
| … | … |
| 8.5 bit | 采样 D7 |
| 9.5 bit | 检查停止位是否为高 |

在 0.5 bit 处二次确认有两个作用：采样位中心，并过滤短暂低电平毛刺。若此时已经恢复高电平，就丢弃本次接收并回到 `RX_IDLE`。

数据位采样时，若读到高电平，则执行：

```c
s_rx.data |= (1U << s_rx.bit);
```

由于 `s_rx.bit` 从 0 递增，最终自然按低位优先还原出一个字节。停止位正确时才把该字节交给接收缓冲区；停止位为低时，本项目会直接丢弃该帧，当前尚未记录 framing error。

### 8.3 RX 定时器回调伪代码

项目的 RX GPTimer 每隔 `SIM_UART_BIT_US_HALF` 触发一次 `timer_on_alarm_cb()`。偶数半位只计时不采样；奇数半位依次处理起始位、8 个数据位和停止位：

```c
timer_on_alarm_cb(timer) {
    s_rx.half_tick++;

    if ((s_rx.half_tick & 1U) == 0) {
        return false;  // 偶数半位跳过
    }

    if (s_rx.state == RX_START) {
        if (read_gpio(SIM_UART_RX_PIN) != LOW) {
            // 0.5 bit 处已恢复高电平，判定为假起始位
            s_rx.state = RX_IDLE;
            stop_timer(timer);
            clear_gpio_interrupt_status(SIM_UART_RX_PIN);
            enable_gpio_interrupt_on_core(
                SIM_UART_RX_PIN, s_gpio_isr_core);
            return false;
        }

        s_rx.state = RX_DATA;
    } else if (s_rx.state == RX_DATA) {
        if (read_gpio(SIM_UART_RX_PIN) == HIGH) {
            s_rx.data |= (1U << s_rx.bit);
        }

        s_rx.bit++;
        if (s_rx.bit >= SIM_UART_DATA_BITS) {
            s_rx.state = RX_STOP;
        }
    } else if (s_rx.state == RX_STOP) {
        if (read_gpio(SIM_UART_RX_PIN) == HIGH) {
            send_byte_to_ring_buffer_from_isr(
                s_rx_buffer, s_rx.data);  // 当前未检查入队结果
        }
        // 停止位为低时直接丢弃，当前没有 framing error 计数

        s_rx.state = RX_IDLE;
        stop_timer(timer);
        clear_gpio_interrupt_status(SIM_UART_RX_PIN);
        enable_gpio_interrupt_on_core(
            SIM_UART_RX_PIN, s_gpio_isr_core);
    }

    return false;
}
```

假起始位和停止位处理结束时，都必须先停止 RX GPTimer，再清除 GPIO 中断状态，最后在初始化时记录的 CPU core 上重新使能 GPIO11 中断。否则后续字节可能无法再次触发接收。

### 8.4 任务侧读取伪代码

`sim_uart_recv()` 是非阻塞字节流接口。它会循环取走当前 Ring Buffer 中已有的数据，但不会等待将来到达的字节：

```c
sim_uart_recv(data, len) {
    if (data == NULL || len == 0 || s_rx_buffer == NULL) {
        return -1;
    }

    read_len = 0;

    while (read_len < len) {
        item = ring_buffer_receive_up_to(
            s_rx_buffer,
            wait_ticks = 0,
            max_len = len - read_len,
            out item_len);

        if (item == NULL) {
            break;  // 当前没有更多数据，立即返回
        }

        copy(data + read_len, item, item_len);
        read_len += item_len;
        return_ring_buffer_item(s_rx_buffer, item);
    }

    return read_len;  // 0 表示当前无数据，不是错误
}
```

## 9. 中断与任务：怎样划分职责

中断服务程序（ISR）应短小、确定，不应执行可能阻塞或耗时不可控的工作。软件 UART 中的合理分工是：

| 位置 | 适合做的工作 | 不适合做的工作 |
| --- | --- | --- |
| GPIO ISR | 识别起始沿、启动接收定时器、切换状态 | 日志、字符串处理、协议解析 |
| 定时器 ISR | 推进收发状态机、读写 GPIO、把已收字节入队 | 等待锁、动态内存、长循环 |
| 任务上下文 | 从缓冲区取数据、协议分帧、业务处理 | 依赖精确位时序的工作 |

部分实时系统会要求 ISR 调用的函数和访问的数据处于 IRAM/DRAM，避免 Flash cache 暂不可用时发生异常。具体要求取决于芯片、SDK 和中断配置，但原则不变：ISR 调用链必须满足平台的中断上下文约束。

## 10. 用缓冲区连接 ISR 与上层

接收 ISR 是数据生产者，应用任务是数据消费者。两者的运行速度不一定相同，因此应在中间设置 Ring Buffer 或队列：

```text
RX ISR（生产字节） → Ring Buffer/Queue → 任务（消费字节）
```

ISR 中应使用操作系统提供的 `...FromISR()` 版本 API。当前项目实际调用为：

```c
xRingbufferSendFromISR(s_rx_buffer,
                       &s_rx.data,
                       sizeof(s_rx.data),
                       NULL);
```

最后一个参数传入 `NULL`，因此当前实现不会通过该调用请求立即调度被唤醒的高优先级任务，同时也没有检查入队是否成功。任务侧提供的非阻塞字节流接口为：

```c
int sim_uart_recv(uint8_t *data, size_t len);
```

- 正数：本次实际读取到的字节数。
- `0`：当前没有数据，不等于错误。
- 负数：参数无效或驱动未初始化等错误。

UART 驱动提供的是连续字节流，而不是天然的“消息”。上层协议应自行依据换行符、固定长度、长度字段、空闲时间或 CRC 等规则分帧。缓冲区满时必须有明确策略：丢弃新字节、丢弃旧数据、通知上层或累计溢出计数；不能默认数据永远不会丢失。

## 11. 发送接口与完成通知

当前项目的同步发送接口为：

```c
int sim_uart_send(const uint8_t *data, size_t len);
```

它的典型流程为：获取 TX mutex → 逐字节启动状态机 → 等待本字节发送完成 → 释放 mutex。

不要用无限 `taskYIELD()` 或空循环等待 `TX_IDLE`。更好的做法是让 TX ISR 在停止位结束时通过任务通知、信号量或事件位唤醒等待任务，并为等待设置超时。这样既减少无效调度，也能在定时器故障或状态机异常时把错误返回给调用者。

如果需要异步发送，可进一步建立 TX 队列：任务把数据放入队列，发送状态机在空闲时自动取下一个字节。该设计吞吐量更好，但需要处理队列所有权、发送完成回调和关闭驱动时的未发送数据。

## 12. 并发、可见性与状态安全

软件 UART 的状态会同时被任务和 ISR 访问，至少需要区分以下问题：

- **互斥**：多个发送任务不能同时改写同一份 TX 数据和状态。
- **可见性**：ISR 修改的状态应能被任务正确获取；`volatile` 可避免某些编译器优化，但不自动提供完整同步和原子性。
- **临界区**：任务更新与 ISR 相关的多个字段时，可能需要平台提供的临界区保护。
- **生命周期**：初始化失败要回滚已申请资源；应提供明确的重复初始化和 `deinit` 约定。

推荐把状态机字段集中放入 TX/RX 结构体，并只允许有限的状态转移。这样既便于检查非法状态，也方便将来增加错误计数、超时和诊断信息。

## 13. 一个最小配置与 API 示例

下面展示的是学习用接口形态，不绑定某个具体芯片或 SDK：

```c
typedef struct {
    int tx_pin;
    int rx_pin;
    uint32_t baudrate;
    size_t rx_buffer_size;
} uart_soft_config_t;

int uart_soft_init(const uart_soft_config_t *config);
int uart_soft_send(const uint8_t *data, size_t len, uint32_t timeout_ms);
int uart_soft_recv(uint8_t *data, size_t len);
void uart_soft_deinit(void);
```

初学阶段建议先固定为 8N1 和一个中低波特率，再逐步扩展数据位、校验位、停止位和异步发送。不要只通过宏修改“数据位数”就宣称支持新格式：状态变量宽度、状态机计数、停止位判断和错误处理都要一并适配。

## 14. 软件 UART 的边界与演进方向

软件 UART 的主要限制是对中断延迟敏感。其他高优先级中断、临界区、缓存相关操作都会影响定时器回调的实际执行时刻；波特率越高，这个问题越明显。它还会持续消耗 CPU 中断时间，并占用定时器资源。

一个可逐步完善的学习方案是：

1. 固定 8N1，实现起始位、8 个数据位和停止位。
2. 用下降沿同步、位中心采样，加入假起始位和停止位错误判断。
3. 用 Ring Buffer 连接 ISR 与任务，定义缓冲区溢出策略。
4. 为 TX 增加完成通知和超时，避免忙等。
5. 增加错误统计：假起始、framing error、缓冲区溢出、定时器操作失败。
6. 明确初始化、反初始化和异常回滚的资源生命周期。
7. 需要更高可靠性或性能时，迁移到硬件 UART；它通常提供 FIFO、硬件采样、错误检测、事件机制和可选流控。

## 15. 核心要点回顾

- UART 通过起始位重新同步每个字符的接收时序，因此不需要共享时钟线。
- 8N1 的一个字节占 10 bit；9600 baud 的理论载荷上限约为 960 byte/s。
- TX 在每个 bit 周期输出起始位、D0 到 D7 和停止位。
- RX 先用下降沿捕获起始位，再在 0.5、1.5、2.5…bit 等位中心采样。
- 接收期间关闭下降沿中断，避免把数据位跳变误判为新帧。
- ISR 负责精确、短小的状态推进；任务负责缓冲读取和协议处理。
- mutex 解决发送并发，Ring Buffer 解决 ISR 与任务之间的速度差，但两者都不能替代完整的错误处理和生命周期设计。

理解以上结构后，再阅读任意平台的硬件 UART 驱动，会更容易看懂其中的 FIFO、采样、状态寄存器、中断和事件队列分别替软件完成了什么。
