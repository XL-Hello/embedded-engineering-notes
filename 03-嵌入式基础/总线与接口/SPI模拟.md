# ESP32-S3 SPI 实现入门

本文从两个维度学习 SPI：先认识 ESP32-S3 的硬件 SPI 资源、引脚规则和 ESP-IDF 基础用法；再用 GPIO 和定时延时实现一个学习用的模拟 SPI 主机，以看清一次传输中 CS、SCLK、MOSI、MISO 分别在何时工作。

> 结论先行：ESP32-S3 面向应用开放的是 **SPI2、SPI3 两个通用 SPI（GPSPI）控制器**，均可由 ESP-IDF 配置为主机或从机。SPI0、SPI1 用于封装内或封装外 Flash/PSRAM 的访问，不应分配给普通外设。模拟 SPI 不是新增硬件 SPI，而是 CPU 依次翻转 GPIO 和采样 GPIO 的软件实现，适合理解协议及低速、简单场景。

## 1. ESP32-S3 的硬件 SPI 资源

### 1.1 控制器如何分工

ESP32-S3 共集成 4 个 SPI 控制器，但不能把“有 4 个控制器”理解成“有 4 条可随意使用的 SPI 总线”。SPI0、SPI1 分别服务于 Flash/PSRAM 的底层访问；应用层常规外设应使用 SPI2、SPI3。

| 控制器 | 角色 | 是否建议给业务外设使用 | 说明 |
| --- | --- | --- | --- |
| SPI0 | SPI Memory | 否 | 供 GDMA 控制器和 Cache 访问封装内或封装外 Flash/PSRAM |
| SPI1 | SPI Memory | 否 | 供 CPU 访问封装内或封装外 Flash/PSRAM |
| SPI2（`SPI2_HOST`） | GPSPI | 是 | 通用 SPI；经 GDMA 分配 DMA 通道，可配置为主机或从机 |
| SPI3（`SPI3_HOST`） | GPSPI | 是 | 另一套通用 SPI；经 GDMA 分配 DMA 通道，可配置为主机或从机 |

SPI2 和 SPI3 各有独立寄存器、FIFO、时钟和信号路径，因此可以同时服务两组互不相同的外设。例如 SPI2 连接显示屏，SPI3 连接 ADC 或射频芯片。它们不互相抢占控制器；真正经常冲突的是 GPIO、DMA、板载 Flash/PSRAM 或其他外设已占用的资源。

需要特别区分“片上存储器控制器”和两套通用 SPI 外设的能力：

| 控制器 | 支持的接口模式 | 关键能力与限制 |
| --- | --- | --- |
| SPI0 / SPI1 | SPI、Dual SPI、Quad SPI、Octal SPI、QPI、OPI | 仅用于 Flash/PSRAM。八线模式支持 SDR、DDR，最高 120 MHz；按字节传输 |
| SPI2 | SPI、Dual SPI、Quad SPI、Octal SPI、QPI、OPI | 主机/从机均支持；可配 CPOL、CPHA、位序和时钟；按字节传输；有 6 路 SPI_CS |
| SPI3 | SPI、Dual SPI、Quad SPI、QPI | 主机/从机均支持；可配 CPOL、CPHA、位序和时钟；按字节传输；有 3 路 SPI_CS；**不支持 Octal SPI 或 OPI** |

SPI2、SPI3 的时钟与传输模式限制如下。表中的“双线全双工”对应常规 MOSI/MISO 同时收发；“半双工”由若干数据线分时读写。

| 控制器 | 角色 | 全双工 | 半双工 | 其他限制 |
| --- | --- | --- | --- | --- |
| SPI2 | 主机 | 双线：最高 80 MHz；八线：仅 SDR | 单线、双线、四线、八线：最高 80 MHz | 八线半双工：SDR 最高 80 MHz，DDR 最高 40 MHz；CS 建立/保持时间可配 |
| SPI2 | 从机 | 双线：最高 60 MHz；八线：仅 SDR | 单线、双线、四线：最高 60 MHz；八线仅 SDR | — |
| SPI3 | 主机 | 双线：最高 80 MHz | 单线、双线、四线：最高 80 MHz | CS 建立/保持时间可配 |
| SPI3 | 从机 | 双线：最高 60 MHz | 单线、双线、四线：最高 60 MHz | — |

因此，外接 Octal/OPI 器件时只能选 SPI2，不能选 SPI3；SPI2 的八线全双工和从机八线模式均只支持 SDR。使用 SPI2/SPI3 驱动外部 Quad/Octal 器件时，需配置全部数据 GPIO，并为相应事务设置 `SPICOMMON_BUSFLAG_QUAD` / `SPICOMMON_BUSFLAG_OCTAL` 和 `SPI_TRANS_MODE_QIO` / `SPI_TRANS_MODE_OCT` 等标志；其中 Octal 相关配置只适用于 SPI2，并应确认所用 ESP-IDF 版本和目标器件协议支持该模式。

### 1.2 SPI2/SPI3 能做什么

通用 SPI 控制器可以作为主机或从机使用。常规四线 SPI 使用以下信号：

| 信号 | 主机视角含义 | 方向（主机为中心） | 作用 |
| --- | --- | --- | --- |
| SCLK / CLK | Serial Clock | 主机输出 | 每个 bit 的节拍，由主机产生 |
| MOSI | Master Out, Slave In | 主机 → 从机 | 主机发出的数据 |
| MISO | Master In, Slave Out | 从机 → 主机 | 从机返回的数据 |
| CS / SS | Chip Select / Slave Select | 主机 → 从机 | 通常低有效，选中一个从机并界定事务 |

SPI 是**同步串行、全双工**接口：在每个有效时钟周期中，主机可经 MOSI 发出一位，同时经 MISO 读入一位。若设备只需要写（如部分 DAC）或只需要读（如某些 ADC 读阶段），仍可省略对应数据线或在不需要的方向填充无意义数据。

除标准双线全双工模式外，SPI2 主机支持 Dual、Quad、Octal、QPI、OPI，SPI3 主机支持 Dual、Quad、QPI。多线模式通常用于半双工读或写阶段：命令、地址、dummy 与数据各使用几条线，均由目标器件协议和 ESP-IDF 事务标志决定。SPI2 的八线全双工仅支持 SDR；其八线半双工支持 SDR（最高 80 MHz）或 DDR（最高 40 MHz）。入门时先掌握标准 MOSI/MISO 四线 SPI。硬件 FIFO 适合短传输；主机启用 DMA 后，传输长度主要受可用 DMA 内存和驱动配置的 `max_transfer_sz` 限制。DMA 缓冲区应位于 DMA-capable 内存；ESP-IDF 也支持按相应事务标志直接使用 PSRAM 数据。

### 1.3 引脚：可重映射，但要先检查板级资源

SPI2、SPI3 的信号可以经 GPIO Matrix 映射到合适的空闲 GPIO。ESP-IDF 在 `spi_bus_initialize()` 的 `spi_bus_config_t` 中填入引脚即可完成配置。若所有使用的信号都使用某组直连 IO_MUX 引脚，驱动可走 IO_MUX；只要其中一个信号走 GPIO Matrix，该总线信号便会统一走 Matrix。

ESP32-S3 的 SPI2 直连 IO_MUX 引脚如下。它们是高速或固定板级设计时的优先选择，**不是唯一可用的引脚**。

| SPI2 信号 | 默认 IO_MUX GPIO |
| --- | --- |
| CS0 | GPIO10 |
| SCLK | GPIO12 |
| MISO | GPIO13 |
| MOSI | GPIO11 |
| WP（Quad 数据线 2） | GPIO14 |
| HD（Quad 数据线 3） | GPIO9 |

对 ESP32-S3 的 **SPI 主机**，在总线频率不高于 40 MHz 时，GPIO Matrix 与 IO_MUX 的行为通常相同；更高频率时应优先使用 IO_MUX 引脚，并以芯片数据手册、外设时序和实测裕量为准。SPI 从机的对应阈值和最高时钟要求不同，不能直接套用此结论。实际选脚还必须避开：

- 板载 Flash/PSRAM、USB、下载电路、显示屏等已经占用的 GPIO。
- 启动配置（strapping）相关 GPIO，避免外部器件的电平影响上电启动。
- 输入专用脚（若所选封装具有）承担 MOSI、SCLK、CS 等输出信号。
- 同一 GPIO 被两个外设同时驱动，或电压域、上拉电阻与从设备要求不匹配。

一个总线可以挂多个从机：SCLK、MOSI、MISO 通常共用，每个从机各用一根独立 CS。按芯片技术规格，SPI2 有 6 路 SPI_CS，SPI3 有 3 路 SPI_CS；从设备更多时，应用也可把 CS 当普通 GPIO 手动控制。实际可由所用 ESP-IDF 驱动分配的硬件 CS 数量，还应以该版本驱动的限制为准。

### 1.4 主机、从机与事务边界

SPI 没有 UART 那样固定的起始位、停止位或统一的“字节帧格式”。一次通信通常由主机拉低 CS 开始、拉高 CS 结束：

```text
CS    ──────┐                         ┌──────
            └─────────────────────────┘
SCLK  ───────┐_┌─┐_┌─┐_┌─┐_┌─┐_┌─┐──────
             └─┘ └─┘ └─┘ └─┘ └─┘
MOSI       C7 C6 C5 C4 C3 C2 C1 C0       （主机发送）
MISO       R7 R6 R5 R4 R3 R2 R1 R0       （从机返回）
```

CS 有效期间，主机输出时钟；双方依据约定的 SPI 模式在某个边沿改变数据、在另一个边沿采样数据。命令、地址、dummy cycle、数据长度、CS 是否要在多段命令之间保持有效，完全由具体从设备的数据手册规定。

### 1.5 SPI 模式：CPOL 与 CPHA

SPI 模式由时钟极性 CPOL 和时钟相位 CPHA 决定，共有 0～3 四种。二者必须在主从双方一致。

| 模式 | CPOL | CPHA | SCLK 空闲电平 | 采样边沿 |
| --- | ---: | ---: | --- | --- |
| 0 | 0 | 0 | 低 | 第一个（上升）边沿 |
| 1 | 0 | 1 | 低 | 第二个（下降）边沿 |
| 2 | 1 | 0 | 高 | 第一个（下降）边沿 |
| 3 | 1 | 1 | 高 | 第二个（上升）边沿 |

本文后续模拟程序固定使用最常见的 **Mode 0、MSB first、8 bit/word、CS 低有效**。Mode 0 下 SCLK 空闲为低，主机先准备 MOSI，再产生上升沿；双方在上升沿采样，并在下降沿准备下一位。

### 1.6 本节资料依据

- 《ESP32-S3-WROOM-1 & WROOM-1U 技术规格书》v1.8，5.2.1.5“串行外设接口（SPI）”（本文 SPI 资源、模式、速率与 CS 数量均以此为准）
- [ESP-IDF：ESP32-S3 SPI Master Driver](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/spi_master.html)
- [ESP-IDF：ESP32-S3 SPI Slave Driver](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/spi_slave.html)
- [ESP32-S3 技术参考手册与数据手册入口](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/hw-reference/index.html)

## 2. ESP-IDF 硬件 SPI 的基础用法

### 2.1 驱动对象：总线、设备、事务

ESP-IDF 把 SPI 主机使用过程分为三个层次：

```text
SPI2_HOST（一个硬件控制器）
       │ spi_bus_initialize()
       ▼
SPI 总线（SCLK/MOSI/MISO/DMA/中断资源）
       │ spi_bus_add_device()
       ▼
SPI 设备句柄（某个 CS、模式、时钟、命令位数）
       │ spi_device_transmit()
       ▼
一次事务（命令 + 地址 + TX + RX）
```

- **总线**描述共享的物理信号和主机资源，初始化一次。
- **设备**描述挂在总线上的某一颗从机，例如其 CS、Mode、时钟频率和命令/地址位宽；多个从机可共享一个总线。
- **事务**描述实际的一次传输，可只写、只读或同时收发。

### 2.2 最小主机示例：Mode 0 写一个寄存器

下面示例用 SPI2 向一个典型寄存器型器件写入 `0x5A`。`0x20` 是示例寄存器地址，实际命令格式必须按目标芯片数据手册修改。

```c
#include "driver/spi_master.h"
#include "esp_err.h"

#define SPI_HOST       SPI2_HOST
#define PIN_NUM_MOSI   GPIO_NUM_11
#define PIN_NUM_MISO   GPIO_NUM_13
#define PIN_NUM_SCLK   GPIO_NUM_12
#define PIN_NUM_CS     GPIO_NUM_10

static spi_device_handle_t s_dev;

void spi_example_init(void)
{
    spi_bus_config_t buscfg = {
        .mosi_io_num = PIN_NUM_MOSI,
        .miso_io_num = PIN_NUM_MISO,
        .sclk_io_num = PIN_NUM_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 0,       // DMA 下默认最大 4092 字节
    };
    spi_device_interface_config_t devcfg = {
        .clock_speed_hz = 1 * 1000 * 1000, // 1 MHz，先从低速验证
        .mode = 0,                          // CPOL=0、CPHA=0
        .spics_io_num = PIN_NUM_CS,
        .queue_size = 1,
    };

    ESP_ERROR_CHECK(spi_bus_initialize(SPI_HOST, &buscfg, SPI_DMA_CH_AUTO));
    ESP_ERROR_CHECK(spi_bus_add_device(SPI_HOST, &devcfg, &s_dev));
}

esp_err_t spi_example_write_reg(void)
{
    const uint8_t tx_data[] = {0x20, 0x5A}; // 示例：地址、写入值
    spi_transaction_t trans = {
        .length = sizeof(tx_data) * 8,      // 注意单位是 bit，不是 byte
        .tx_buffer = tx_data,
    };

    return spi_device_transmit(s_dev, &trans);
}
```

`spi_device_transmit()` 是同步接口：调用返回时，该事务已完成。硬件驱动会按设备配置控制 CS、产生 SCLK 并完成移位/采样。一次事务期间发送和接收是同步进行的；若 `rx_buffer` 为 `NULL`，接收的数据被忽略。

### 2.3 读寄存器：发送 dummy 字节来产生时钟

SPI 的从机不能自行发起传输。即使目标是“读取”，主机仍须发送时钟；常见做法是在读阶段发出一个或多个 dummy 字节。以下示例采用“命令/寄存器控制字 + dummy + 读回一字节”的常见形式，具体字节数和控制字编码仍应以器件手册为准：

```c
esp_err_t spi_example_read_reg(uint8_t reg, uint8_t *value)
{
    uint8_t tx_data[] = {0x80 | reg, 0xFF}; // 示例：命令/寄存器控制字、dummy
    uint8_t rx_data[sizeof(tx_data)] = {0};
    spi_transaction_t trans = {
        .length = sizeof(tx_data) * 8,
        .tx_buffer = tx_data,
        .rx_buffer = rx_data,
    };

    esp_err_t err = spi_device_transmit(s_dev, &trans);
    if (err == ESP_OK) {
        *value = rx_data[1]; // 控制字阶段的回读通常无效，dummy 字节期间读到返回值
    }
    return err;
}
```

不要假定所有芯片的读命令都是 `0x80 | reg`，也不要假定读回值总在 `rx_data[1]`。有的器件要求 CS 在命令和数据间保持低，有的要求重新拉高再拉低；有的需要 8 个或更多 dummy clock。SPI 本身只定义电气和移位机制，命令语义由从设备定义。

### 2.4 轮询、队列与 DMA

常用的事务提交方式如下：

| 接口 | 场景 | 特点 |
| --- | --- | --- |
| `spi_device_transmit()` | 入门、低频控制命令 | 同步等待，最容易使用 |
| `spi_device_polling_transmit()` | 不希望切换任务的短事务 | 轮询完成；不可与未完成的中断事务混用 |
| `spi_device_queue_trans()` + `spi_device_get_trans_result()` | 连续数据流、显示屏刷新 | 异步排队，提高吞吐；必须回收每个已完成事务 |

DMA 适合显示帧、音频块或较长数据块。启用 DMA 时，TX/RX 缓冲区需要满足 DMA 内存要求；若是很短的事务，可使用 `SPI_TRANS_USE_TXDATA` / `SPI_TRANS_USE_RXDATA` 和事务结构体的内嵌 4 字节缓冲区，避免额外分配。无论采用何种方式，`spi_transaction_t.length` 和 `rxlength` 的单位均为 **bit**，这是最常见的长度配置错误来源。

SPI 中断服务程序固定运行在调用 `spi_bus_initialize()` 的 CPU core 上。因此不要长期阻塞该 core；否则已排队的 SPI 中断事务不能及时处理。若设置 `ESP_INTR_FLAG_IRAM`，回调函数及其调用链也必须满足 IRAM 中断上下文要求。

### 2.5 硬件 SPI 的排错顺序

1. 先确认目标芯片电压、接线、共地和 CS 极性正确。
2. 再确认 Mode 0/1/2/3、位序（MSB/LSB first）、最大 SCLK、命令/地址/dummy 时钟符合器件手册。
3. 用 100 kHz～1 MHz 低速先读固定 ID 或状态寄存器，成功后再逐步提高频率。
4. 逻辑分析仪同时观察 CS、SCLK、MOSI、MISO，重点检查采样边沿前后数据是否稳定。
5. 仅在确有需要时再引入 DMA、队列、Quad/Octal 和复杂的多事务时序。

## 3. 入门版模拟 SPI：用 GPIO 看见移位过程

### 3.1 目标与范围

下面实现一个**软件 SPI 主机**，固定为：Mode 0、MSB first、8 bit、CS 低有效，支持一次交换一个字节。它不使用硬件 SPI 控制器、FIFO、DMA 或中断，而是由 CPU 按顺序操作 GPIO。

```text
应用调用 sim_spi_transfer_byte(0xA5)
          │
          ▼
CS 拉低 → 逐位设置 MOSI → SCLK 上升沿采样 MISO → SCLK 下降沿 → CS 拉高
          │
          ▼
返回同时收到的 8 bit 数据
```

这是理解 SPI 的好起点，但不适合高速度、长数据流或实时性要求高的产品功能：每一个边沿都依赖 CPU 调度与延时函数，任务切换和中断会造成时钟抖动。工程产品优先使用硬件 SPI。

### 3.2 Mode 0 的一个 bit 到底发生什么

以待发送字节 `0xA5`（二进制 `1010 0101`）的最高位为例：

```text
初始：CS=1，SCLK=0

1. CS 拉低，选中从机
2. MOSI 输出 bit7（1），保持稳定
3. SCLK 从 0 拉到 1：主机和从机都在此上升沿采样输入
4. 主机读取 MISO，得到从机在该位送出的数据
5. SCLK 从 1 拉到 0：双方可在此后准备下一 bit
6. 重复 2～5 共 8 次
7. CS 拉高，事务结束；SCLK 保持空闲低电平
```

注意第 3 步：主机的上升沿既是“从机采样 MOSI”的时刻，也是“主机采样 MISO”的时刻。所谓全双工，正是两条数据线在同一组时钟边沿并行移位，而不是先完整发送再完整接收。

### 3.3 可直接放入 ESP-IDF 工程的最小代码

以下代码使用 `esp_rom_delay_us()` 产生半周期延时。`SIM_SPI_HALF_PERIOD_US` 设为 5 时，理想 SCLK 约为 100 kHz；实际频率会受函数调用、CPU、中断和优化等级影响，因此它是教学和低速验证用值，而不是精确时钟源。

```c
#include <stddef.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_rom_sys.h"

#define SIM_SPI_PIN_CS     GPIO_NUM_4
#define SIM_SPI_PIN_SCLK   GPIO_NUM_5
#define SIM_SPI_PIN_MOSI   GPIO_NUM_6
#define SIM_SPI_PIN_MISO   GPIO_NUM_7

#define SIM_SPI_HALF_PERIOD_US  5

static inline void sim_spi_delay_half_period(void)
{
    esp_rom_delay_us(SIM_SPI_HALF_PERIOD_US);
}

void sim_spi_init(void)
{
    gpio_config_t out_cfg = {
        .pin_bit_mask = (1ULL << SIM_SPI_PIN_CS) |
                        (1ULL << SIM_SPI_PIN_SCLK) |
                        (1ULL << SIM_SPI_PIN_MOSI),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config_t in_cfg = {
        .pin_bit_mask = 1ULL << SIM_SPI_PIN_MISO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    ESP_ERROR_CHECK(gpio_config(&out_cfg));
    ESP_ERROR_CHECK(gpio_config(&in_cfg));

    gpio_set_level(SIM_SPI_PIN_CS, 1);    // CS 空闲为高
    gpio_set_level(SIM_SPI_PIN_SCLK, 0);  // Mode 0 空闲为低
    gpio_set_level(SIM_SPI_PIN_MOSI, 0);
}

// Mode 0、MSB first：发送 tx 的同时返回 MISO 收到的字节。
uint8_t sim_spi_transfer_byte(uint8_t tx)
{
    uint8_t rx = 0;

    for (int bit = 7; bit >= 0; --bit) {
        gpio_set_level(SIM_SPI_PIN_MOSI, (tx >> bit) & 1U);
        sim_spi_delay_half_period();

        gpio_set_level(SIM_SPI_PIN_SCLK, 1); // 第一个边沿：采样
        sim_spi_delay_half_period();
        rx = (uint8_t)((rx << 1) |
                       (gpio_get_level(SIM_SPI_PIN_MISO) & 1));

        gpio_set_level(SIM_SPI_PIN_SCLK, 0); // 第二个边沿：准备下一位
        sim_spi_delay_half_period();
    }

    return rx;
}

uint8_t sim_spi_transfer(uint8_t tx)
{
    uint8_t rx;

    gpio_set_level(SIM_SPI_PIN_CS, 0);
    sim_spi_delay_half_period();
    rx = sim_spi_transfer_byte(tx);
    sim_spi_delay_half_period();
    gpio_set_level(SIM_SPI_PIN_CS, 1);

    return rx;
}
```

代码中 `rx = (rx << 1) | miso_bit` 与 MSB first 配套：先采样到的 MISO bit 会在 8 次移位后成为 bit7。若协议是 LSB first，则循环应从 bit 0 到 7，且接收数据应使用 `rx |= miso_bit << bit`。

### 3.4 如何验证，而不是只看代码

最安全的第一步是**不连接真实从机**，仅用导线把 MOSI 接到 MISO（两脚均为 ESP32-S3 GPIO）形成回环。调用：

```c
uint8_t rx = sim_spi_transfer(0xA5);
// 回环正确时，rx 应为 0xA5
```

回环验证了 MOSI 的位序、MISO 采样、SCLK 边沿和 CS 包围范围，但不能验证真实从机的命令格式。接入真实器件时，应先从其“读芯片 ID”示例开始，确认 CS、Mode、时钟频率、读命令和 dummy cycle；不要把任意 MOSI/MISO 短接到外部会驱动该线路的从机上。

逻辑分析仪上的 Mode 0 理想波形应表现为：CS 低期间有 8 个 SCLK 上升沿；MOSI 在每个上升沿之前稳定；MISO 在上升沿附近被主机读入；CS 拉高后 SCLK 回到低电平。若 `rx` 总为 `0x00` 或 `0xFF`，优先检查 MISO 浮空、未共地、CS 未选中或模式不一致。

### 3.5 从单字节到“命令 + 地址 + 数据”

很多 SPI 器件需要在同一段 CS 有效期中连续发送多个字节。可在 `sim_spi_transfer()` 的基础上扩展为：CS 只拉低一次，连续交换多个字节，最后再拉高。

```c
void sim_spi_transfer_buf(const uint8_t *tx, uint8_t *rx, size_t len)
{
    gpio_set_level(SIM_SPI_PIN_CS, 0);
    sim_spi_delay_half_period();

    for (size_t i = 0; i < len; ++i) {
        uint8_t tx_byte = tx ? tx[i] : 0xFF; // 只读时仍要送出时钟
        uint8_t rx_byte = sim_spi_transfer_byte(tx_byte);
        if (rx) {
            rx[i] = rx_byte;
        }
    }

    sim_spi_delay_half_period();
    gpio_set_level(SIM_SPI_PIN_CS, 1);
}
```

例如读取一颗器件的 ID 时，`tx` 可能是 `{READ_ID_CMD, 0xFF, 0xFF, 0xFF}`；前一个字节发送读命令，之后的 `0xFF` 只是提供时钟，真正 ID 出现在哪个 `rx[i]` 取决于器件协议。这里“保持 CS 低”常常是关键：若每发一个字节就调用一次 `sim_spi_transfer()`，从机可能把每个字节都当成一条新命令。

### 3.6 模拟 SPI 的边界与演进

入门实现刻意省略了互斥、超时、DMA、队列和从机模式。继续完善时可按以下顺序推进：

1. 用 mutex 保护一次完整事务，避免多个任务交叉翻转同一组 GPIO。
2. 把 CPOL/CPHA、位序、字宽和 CS 极性做成配置项，并针对 4 种模式分别验证波形。
3. 使用硬件定时器或 RMT 改善时钟均匀性；仍需评估 ISR 延迟。
4. 为真实设备实现命令、地址、dummy、状态轮询与错误处理。
5. 需要稳定高速、连续长传输或多设备并发时，迁移到 SPI2/SPI3 硬件驱动和 DMA。

模拟 SPI 的核心价值不在替代硬件外设，而在于把硬件 SPI 自动完成的动作拆开：拉选中、在正确边沿更新 MOSI、在正确边沿采样 MISO、连续移位 8 次、再释放 CS。理解这些动作后，阅读 ESP-IDF 的 `spi_transaction_t`、Mode 配置、DMA 与队列机制会清晰得多。

## 4. 核心要点回顾

- ESP32-S3 可用于普通外设的是 SPI2、SPI3。SPI2 支持 Single/Dual/Quad/Octal/QPI/OPI，SPI3 支持 Single/Dual/Quad/QPI；Octal/OPI 只能使用 SPI2。两者的主从机速率、SDR/DDR 限制及 SPI_CS 数量见第 1.1 节；SPI0/1 属于 Flash/PSRAM 访问路径，不能当作可随意映射 GPIO 的通用 SPI 使用。
- SPI 由 CS、SCLK、MOSI、MISO 组成；主机提供时钟，数据收发在同一组时钟中同时进行。
- SPI 没有统一帧格式；Mode、位序、命令、地址、dummy cycle 与 CS 时序都由主从协议约定。
- ESP-IDF 的基本顺序是：初始化总线 → 添加设备 → 提交事务；长度字段用 bit 计。
- Mode 0 下 SCLK 空闲为低，在上升沿采样、下降沿准备下一位。
- GPIO 模拟 SPI 能直观看清每个边沿的作用，但时序受 CPU 与中断影响，不应用于需要稳定高速传输的场合。
