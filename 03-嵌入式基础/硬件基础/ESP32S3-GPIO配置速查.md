# GPIO 配置基础与 `gpio_config_t` 速查

> 适用：ESP-IDF。不同 ESP-IDF 版本的结构体成员可能略有增加，但 GPIO 的配置思路相同。

GPIO（General Purpose Input/Output）并不是只有“高、低电平”两种用法。每个引脚至少要先决定：它要**读**外部信号、**输出**信号，还是两者都要；空闲时电平由谁保持；以及是否需要中断。`gpio_config_t` 是 ESP-IDF 用来一次性描述这些基本属性的配置结构体。

## 1. 初次使用时，先用这个流程选 GPIO

1. **确认硬件连接**：看开发板原理图，而不是只看芯片管脚图。引脚可能已接 LED、按键、外部上拉、Flash/PSRAM 或 USB。
2. **确认外设需求**：单向输入、推挽输出、开漏输出、ADC、I2C、UART、PWM 等。能使用外设驱动时，优先使用外设驱动；不要为了使用 GPIO 而手写软件模拟。
3. **检查限制**：避开启动绑带（strapping）脚和板载 Flash/PSRAM 占用脚；ESP32-S3 的 GPIO0、GPIO3、GPIO45、GPIO46 与启动配置有关，GPIO46 还是仅输入脚。USB D-/D+ 常接 GPIO19/GPIO20。实际可用性以具体模组和开发板原理图为准。
4. **决定空闲电平**：输入脚不能悬空。若电路未提供外部上拉/下拉，就打开内部上下拉；I2C 等总线通常仍应使用合适的外部上拉。
5. **再决定中断**：按键、告警等异步信号可用边沿中断；高速或连续采样通常不应依赖 GPIO 中断。

常用查阅入口：芯片 Datasheet 的 *IO MUX / GPIO* 章节、开发板原理图、ESP-IDF 的 GPIO API 文档，以及工程中已使用的管脚定义。四者同时确认，才能避免“代码正确但硬件脚选错”。

## 2. `gpio_config_t` 的核心成员

典型配置如下：

```c
#include "driver/gpio.h"

gpio_config_t io_conf = {
    .pin_bit_mask = 1ULL << GPIO_NUM_4,      // 可一次配置多个脚：按位或即可
    .mode = GPIO_MODE_INPUT,
    .pull_up_en = GPIO_PULLUP_ENABLE,
    .pull_down_en = GPIO_PULLDOWN_DISABLE,
    .intr_type = GPIO_INTR_DISABLE,
};
ESP_ERROR_CHECK(gpio_config(&io_conf));
```

| 成员 | 作用 | 实用提醒 |
| --- | --- | --- |
| `pin_bit_mask` | 要配置的 GPIO 位图 | 使用 `1ULL << GPIO_NUM_x`，必须是 64 位的 `1ULL`，不要写成 `1 << x`。多个脚可写 `(1ULL << A) | (1ULL << B)`。|
| `mode` | 输入/输出/开漏能力 | 是最关键的选择，详见下一节。|
| `pull_up_en` | 使能内部弱上拉 | 适用于按键、简单逻辑输入等；不是精确电阻，也不能替代总线所需的外部上拉。|
| `pull_down_en` | 使能内部弱下拉 | 用来给未按下、未驱动的输入一个确定低电平。通常不要与内部上拉同时启用。|
| `intr_type` | GPIO 中断触发方式 | 如上升沿、下降沿、任意边沿、低/高电平；配置后还要安装 ISR 服务并添加处理函数。|

`gpio_config()` 会按这份结构体整体配置引脚。之后可用 `gpio_set_level()` 写电平、`gpio_get_level()` 读电平。若只需临时改变方向，可使用 `gpio_set_direction()`；若只需调整内部上下拉，可使用 `gpio_set_pull_mode()`。

## 3. GPIO 模式怎么选：含经典使用场景

| 模式 | 含义 | 典型场景 | 使用要点 |
| --- | --- | --- | --- |
| `GPIO_MODE_DISABLE` | 禁用数字输入、输出 | 将引脚交给 ADC/低功耗用途前的数字功能清理 | 它不等同于“自动变成模拟输入”；ADC 请继续按 ADC 驱动配置。|
| `GPIO_MODE_INPUT` | 只读外部电平 | 按键、霍尔/限位开关、模块状态脚、外部中断 | 输入不得悬空；按键常用内部上拉，按下接地。|
| `GPIO_MODE_OUTPUT` | 只推挽输出 | LED、继电器驱动器的逻辑输入、片选 CS、普通控制脚 | 可主动输出高或低；不要与另一个推挽输出直接相连。|
| `GPIO_MODE_OUTPUT_OD` | 只开漏输出 | 外接上拉的告警线、共享“就绪”线、单向开漏控制 | 输出 `0` 时主动拉低，输出 `1` 时是高阻态，必须由外部/内部上拉得到高电平。|
| `GPIO_MODE_INPUT_OUTPUT` | 推挽输出，同时可读回脚电平 | 单线协议调试、需核对实际输出的控制脚 | 能读到的是管脚实际电平，可能与期望输出不同（例如被外部拉住）。|
| `GPIO_MODE_INPUT_OUTPUT_OD` | 开漏输出，同时可读总线电平 | I2C SDA/SCL、共享的双向单线总线 | 经典的 I2C GPIO 配置；既能释放总线，也能读取其他设备拉低的结果。|

### 3.1 `GPIO_MODE_INPUT`：按键输入

最常见接法是：GPIO 通过按键接 GND，未按下时由上拉保持高电平。

```c
gpio_config_t key = {
    .pin_bit_mask = 1ULL << GPIO_NUM_4,
    .mode = GPIO_MODE_INPUT,
    .pull_up_en = GPIO_PULLUP_ENABLE,
    .pull_down_en = GPIO_PULLDOWN_DISABLE,
    .intr_type = GPIO_INTR_NEGEDGE,  // 按下时由高变低
};
ESP_ERROR_CHECK(gpio_config(&key));
```

机械按键会抖动。中断只负责通知“发生了变化”，消抖应在任务、定时器或软件状态机中完成；不要在 ISR 内延时等待消抖。

### 3.2 `GPIO_MODE_OUTPUT`：LED 和普通控制脚

```c
gpio_config_t led = {
    .pin_bit_mask = 1ULL << GPIO_NUM_48,
    .mode = GPIO_MODE_OUTPUT,
    .pull_up_en = GPIO_PULLUP_DISABLE,
    .pull_down_en = GPIO_PULLDOWN_DISABLE,
    .intr_type = GPIO_INTR_DISABLE,
};
ESP_ERROR_CHECK(gpio_config(&led));
gpio_set_level(GPIO_NUM_48, 1);  // 实际亮灭取决于 LED 是高电平还是低电平有效
```

GPIO 只适合驱动小电流逻辑负载。继电器、电机、大功率 LED 等必须经三极管/MOSFET/专用驱动器，不能直接由 GPIO 供电或带载。

### 3.3 `GPIO_MODE_OUTPUT_OD`：为什么要开漏

推挽输出会主动驱动高、低两种电平；若两个设备在同一根线上分别输出高和低，就可能产生直通电流。开漏输出只有“拉低”和“放手”两种状态：

- 写 `0`：GPIO 导通，把总线拉低；
- 写 `1`：GPIO 变高阻，不主动输出高；
- 总线为高：由上拉电阻提供。

因此，多台设备可安全共用一根线：只要任意设备拉低，结果就是低；只有全部释放，结果才为高。这种关系也叫“线与”（wired-AND，按低有效逻辑理解）。

### 3.4 `GPIO_MODE_INPUT_OUTPUT_OD`：软件模拟 I2C 为什么必须用它

I2C 的 SDA 和 SCL 都是**开漏、带上拉的共享总线**。主机发送高电平时，实际动作不是“推高”，而是**释放总线**，让上拉电阻把线拉高；任意从机都可把线拉低。SDA 由此实现 ACK 和多主仲裁，SCL 则允许从机通过拉低时钟实现 clock stretching。

所以软件模拟 I2C（bit-bang I2C）应把两根线设为 `GPIO_MODE_INPUT_OUTPUT_OD`：既能拉低/释放，又能读取总线真实状态。若误用 `GPIO_MODE_OUTPUT`，主机推高时从机拉低会发生电平冲突，轻则通信失败，重则增加器件受损风险。

```c
#define I2C_SCL GPIO_NUM_9
#define I2C_SDA GPIO_NUM_8

gpio_config_t i2c_gpio = {
    .pin_bit_mask = (1ULL << I2C_SCL) | (1ULL << I2C_SDA),
    .mode = GPIO_MODE_INPUT_OUTPUT_OD,
    .pull_up_en = GPIO_PULLUP_DISABLE,      // 推荐板上为 SDA/SCL 各放外部上拉
    .pull_down_en = GPIO_PULLDOWN_DISABLE,
    .intr_type = GPIO_INTR_DISABLE,
};
ESP_ERROR_CHECK(gpio_config(&i2c_gpio));

// 拉低：写 0；释放并等待上拉形成高电平：写 1。
gpio_set_level(I2C_SDA, 0);
gpio_set_level(I2C_SDA, 1);
while (gpio_get_level(I2C_SCL) == 0) {
    ; // 从机可能正在 clock stretching；实际项目应加入超时
}
```

内部上拉可用于临时验证，但通常较弱且参数离散，无法保证总线的上升时间。正式 I2C 设计应按电压、线长、总线电容和速率选择外部上拉电阻；常见起点是 4.7 kΩ，但不能脱离硬件条件照搬。若不是学习协议或调试异常，优先使用 ESP-IDF 的硬件 I2C 驱动，它支持更可靠的时序和错误处理。

## 4. 上拉、下拉与“悬空”问题

输入引脚电压没有被可靠拉到高或低时，会受噪声影响随机跳变，这就是悬空。选择原则：

- 按键一端接地：GPIO 使用上拉，未按是 `1`，按下是 `0`；
- 按键一端接电源：GPIO 使用下拉，未按是 `0`，按下是 `1`；
- 外部芯片已提供上拉/下拉：一般关闭 ESP32-S3 内部上下拉，避免改变电阻网络；
- I2C：使用外部上拉，且不要启用下拉；
- 推挽输出：通常关闭上下拉；若上电瞬间必须有确定状态，应由外部硬件保证。

## 5. GPIO 中断的最小正确用法

中断适合“事件到了，通知任务处理”，不适合在 ISR 中打印日志、延时、访问会阻塞的驱动。

```c
static void IRAM_ATTR key_isr(void *arg)
{
    BaseType_t higher_priority_task_woken = pdFALSE;
    QueueHandle_t queue = (QueueHandle_t)arg;
    uint32_t gpio_num = GPIO_NUM_4;
    xQueueSendFromISR(queue, &gpio_num, &higher_priority_task_woken);
    if (higher_priority_task_woken) {
        portYIELD_FROM_ISR();
    }
}

// 完成 gpio_config() 后，仅安装一次服务，再为具体 GPIO 注册处理函数。
ESP_ERROR_CHECK(gpio_install_isr_service(0));
ESP_ERROR_CHECK(gpio_isr_handler_add(GPIO_NUM_4, key_isr, event_queue));
```

ISR 及其调用路径需要放在 IRAM/DRAM 的要求会随工程配置而变化；为稳妥起见，让 ISR 保持极短，只把事件投递给任务。

## 6. 常见故障排查清单

1. **电平总是随机变化**：检查输入是否悬空、上拉/下拉方向是否正确、GND 是否共地。
2. **I2C 一直读到低**：检查 SDA/SCL 是否有上拉、地址/供电是否正确、是否有设备一直拉低；用逻辑分析仪观察起始条件和 ACK。
3. **I2C 一直读到高或没有 ACK**：确认总线未接反、外设供电正常、上拉电压与 GPIO 电平兼容，并确认软件在“高电平”时是释放总线而非强推高。
4. **上电后无法启动或下载**：换用非绑带脚，检查 GPIO0、GPIO3、GPIO45、GPIO46 在复位瞬间是否被外部电路拉到不合适的电平。
5. **输出电平不对**：确认 LED/模块是高有效还是低有效，确认引脚没有被外设复用，并测量 GPIO 实际电压而不只看软件变量。

## 7. 使用前速记

> 单向读：`INPUT`；普通单向控制：`OUTPUT`；共享且只允许拉低：`OUTPUT_OD`；既要共享拉低又要读总线：`INPUT_OUTPUT_OD`。任何输入都不要悬空；任何 I2C 都不要用推挽强推高。
