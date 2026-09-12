# 嵌入式 C 语言：回调函数、函数指针表与结构体嵌套

> 回调函数的本质不是“函数反过来调用”，而是**把下一步该执行的行为以函数地址交给框架、驱动或通用模块；在合适的事件或时机，由它间接调用**。嵌入式中常用它解耦硬件驱动和业务逻辑、统一中断/协议事件处理，并用函数指针表和结构体组织可扩展接口。

---

## 1. 先建立整体模型

函数在程序中也有地址。保存这个地址的变量叫**函数指针**；通过函数指针调用函数，就是间接调用。

```text
业务层注册处理函数                 驱动/框架保存函数地址                事件到来时调用
        │                                    │                                │
        ▼                                    ▼                                ▼
button_set_callback(on_button)  ──►  callback = on_button  ──►  callback(event)
```

这里的 `on_button` 是普通函数，`callback` 是函数指针。回调并不是 C 的新语法，而是函数指针的一种使用模式。

```c
#include <stdint.h>

typedef void (*button_callback_t)(uint8_t pin, void *user_data);

static void on_button(uint8_t pin, void *user_data)
{
    (void)user_data;
    /* 根据 pin 处理按键事件 */
}

static button_callback_t s_callback;
static void *s_user_data;

void button_set_callback(button_callback_t callback, void *user_data)
{
    s_callback = callback;
    s_user_data = user_data;
}

void button_irq_handler(uint8_t pin)
{
    if (s_callback != NULL) {
        s_callback(pin, s_user_data);
    }
}
```

调用链是：应用调用 `button_set_callback()` 注册处理函数；中断或驱动检测到事件后，`button_irq_handler()` 再调用该函数。驱动不需要知道具体要点灯、发消息还是记日志。

---

## 2. 指针函数与函数指针：先分清声明

这两个词只差两个字，含义完全不同。C 的声明遵循“从变量名向外读”的规则；括号决定 `*` 先和谁结合。

| 名称 | 典型声明 | 本质 | 调用/使用 |
|---|---|---|---|
| 指针函数 | `int *find(int key);` | **返回指针的函数** | `int *p = find(1);` |
| 函数指针 | `int (*handler)(int key);` | **指向函数的指针变量** | `handler = find_value; handler(1);` |

### 2.1 指针函数：函数返回一个地址

```c
static int s_values[] = { 10, 20, 30 };

int *find_value(int value)
{
    for (size_t i = 0; i < 3; ++i) {
        if (s_values[i] == value) {
            return &s_values[i];
        }
    }
    return NULL;
}

int *p = find_value(20);  /* p 指向数组中的元素 */
```

`find_value` 先与 `()` 结合，所以它是函数；最左侧的 `*` 表示函数返回 `int *`。指针函数本身与回调没有必然关系。

不要返回局部自动变量的地址：

```c
int *wrong(void)
{
    int value = 0;
    return &value;        /* 错误：函数返回后 value 生命周期结束 */
}
```

### 2.2 函数指针：变量保存函数的地址

```c
int add(int a, int b) { return a + b; }
int sub(int a, int b) { return a - b; }

int (*operation)(int, int);  /* operation 是函数指针 */

operation = add;
int sum1 = operation(3, 2);     /* 推荐写法 */
int sum2 = (*operation)(3, 2);  /* 等价，括号不可省 */
```

函数名在大多数表达式中会转换为函数地址，因此 `operation = add;` 和 `operation = &add;` 等价；`operation(3, 2)` 和 `(*operation)(3, 2)` 也等价。为了可读性，工程中通常省略 `&` 与调用时的 `*`。

### 2.3 用 `typedef` 降低声明难度

复杂函数指针应优先起类型别名，接口更易读、也更不容易写错。

```c
typedef int (*operation_t)(int a, int b);
typedef void (*timer_callback_t)(void *arg);

operation_t operation = add;
timer_callback_t timeout_cb;
```

**函数类型必须兼容**：参数个数、每个参数类型、返回类型都应匹配。不要把不兼容的函数强制转换后塞给回调；即使某个编译器“能跑”，调用仍可能是未定义行为，尤其会在不同 ABI、优化等级或 MCU 架构下出问题。

---

## 3. 回调函数：接口设计与执行上下文

一个实用回调接口至少要明确四件事：什么时候调用、在哪个上下文调用、传什么数据、谁负责数据的生命周期。

### 3.1 同步回调：由通用算法决定处理策略

```c
typedef int (*compare_t)(int left, int right);

static int ascending(int left, int right)
{
    return left - right;
}

static void sort2(int *a, int *b, compare_t compare)
{
    if (compare != NULL && compare(*a, *b) > 0) {
        int temp = *a;
        *a = *b;
        *b = temp;
    }
}
```

`sort2()` 负责流程，比较规则由调用者提供。这种回调在 `sort2()` 运行期间立即执行，通常不需要保存回调指针；调用者只需保证回调函数本身有效。

### 3.2 异步回调：常见于中断、定时器和通信驱动

异步回调会被保存，稍后才执行。除了函数地址，通常还应提供 `void *user_data`，避免用全局变量把多实例状态绑死。

```c
typedef void (*uart_rx_callback_t)(const uint8_t *data, size_t len, void *user_data);

struct uart_device {
    uart_rx_callback_t rx_callback;
    void *user_data;
};

void uart_set_rx_callback(struct uart_device *dev,
                          uart_rx_callback_t callback,
                          void *user_data)
{
    if (dev != NULL) {
        dev->rx_callback = callback;
        dev->user_data = user_data;
    }
}

static void uart_rx_done(struct uart_device *dev, const uint8_t *data, size_t len)
{
    if (dev != NULL && dev->rx_callback != NULL) {
        dev->rx_callback(data, len, dev->user_data);
    }
}
```

`user_data` 是不带类型信息的上下文指针。注册方传入状态对象，回调中再转回正确类型：

```c
struct app_context {
    uint32_t rx_count;
};

static void on_uart_rx(const uint8_t *data, size_t len, void *user_data)
{
    struct app_context *ctx = user_data;

    if (ctx == NULL || data == NULL) {
        return;
    }
    ctx->rx_count += len;
}
```

### 3.3 嵌入式回调的高频陷阱

| 问题 | 后果 | 建议 |
|---|---|---|
| 未注册就调用 | 空指针调用，可能 HardFault | 调用前检查是否为 `NULL` |
| `user_data` 指向已释放/已返回的局部对象 | 野指针、随机故障 | 明确所有权；注销后再释放对象 |
| ISR 中执行耗时回调 | 中断延迟增大、丢数据、影响实时性 | ISR 只搬运数据/置标志，交给任务处理 |
| 回调内再次注册、注销或加锁 | 重入、死锁、链表损坏 | 明确是否允许重入；必要时延后修改 |
| 缓冲区在回调返回后失效 | 保存 `data` 后出现悬空引用 | 文档说明数据仅在回调期间有效，或复制数据 |

中断上下文尤其要谨慎：不要在 ISR 回调中阻塞、长时间轮询、做动态内存分配，或调用不允许从中断调用的 RTOS API。更稳妥的模型是 ISR 投递消息/通知任务，由任务回调业务处理函数。

---

## 4. 函数指针表：把分支变成可配置映射

当“命令号/状态”与“处理函数”一一对应时，函数指针表比一长串 `if-else` 或 `switch` 更容易扩展。

### 4.1 同签名函数的顺序表

```c
typedef void (*command_handler_t)(void);

static void cmd_start(void) { /* 启动 */ }
static void cmd_stop(void)  { /* 停止 */ }
static void cmd_reset(void) { /* 复位 */ }

static const command_handler_t s_handlers[] = {
    cmd_start,
    cmd_stop,
    cmd_reset,
};

void command_dispatch(uint8_t command)
{
    if (command < sizeof(s_handlers) / sizeof(s_handlers[0]) &&
        s_handlers[command] != NULL) {
        s_handlers[command]();
    }
}
```

`static const` 表示表仅在当前源文件可见，且表项不可被运行时修改；在许多 MCU 工具链中，这类只读数据可放入 Flash。注意数组下标必须做边界检查，协议命令号也不能默认连续。

### 4.2 命令号不连续：用“键 + 回调”的表

```c
typedef int (*command_handler_t)(const uint8_t *payload, size_t len);

struct command_entry {
    uint8_t command;
    command_handler_t handler;
};

static int handle_ping(const uint8_t *payload, size_t len) { return 0; }
static int handle_set_rate(const uint8_t *payload, size_t len) { return 0; }

static const struct command_entry s_command_table[] = {
    { .command = 0x01, .handler = handle_ping },
    { .command = 0x21, .handler = handle_set_rate },
};

int command_dispatch(uint8_t command, const uint8_t *payload, size_t len)
{
    for (size_t i = 0; i < sizeof(s_command_table) / sizeof(s_command_table[0]); ++i) {
        if (s_command_table[i].command == command) {
            return s_command_table[i].handler(payload, len);
        }
    }
    return -1;  /* 未支持的命令 */
}
```

这种表格常用于协议分发、状态机事件分发和 CLI 命令。表很小时，线性查找最直观；表很大或查找频繁时，再评估排序后二分、直接索引表或哈希，不能为了“看起来高级”牺牲 Flash、RAM 和可维护性。

---

## 5. 结构体嵌套：组织状态、接口和实例

结构体嵌套是指结构体成员本身也是一个结构体。它不是回调专属语法，但与函数指针结合后，可以把一个模块的配置、运行状态和操作集合收拢到同一个对象中。

### 5.1 成员结构体与访问方式

```c
struct gpio_config {
    uint8_t pin;
    uint8_t active_level;
};

struct led {
    struct gpio_config gpio;  /* 嵌入成员，不是指针 */
    uint32_t blink_count;
};

struct led status_led = {
    .gpio = { .pin = 13, .active_level = 1 },
    .blink_count = 0,
};

status_led.gpio.pin = 12;
```

`gpio` 的存储空间属于 `struct led` 对象本身，生命周期与外层对象一致。若改为 `struct gpio_config *gpio;`，则只保存地址，配置对象必须单独存在，并由设计者保证其生命周期。

### 5.2 “状态 + 操作表”：常见驱动抽象

```c
struct i2c_bus;

struct i2c_ops {
    int (*write)(struct i2c_bus *bus, uint8_t addr,
                 const uint8_t *data, size_t len);
    int (*read)(struct i2c_bus *bus, uint8_t addr,
                uint8_t *data, size_t len);
};

struct i2c_bus {
    uintptr_t base_addr;
    const struct i2c_ops *ops;
    void *private_data;
};

int i2c_write(struct i2c_bus *bus, uint8_t addr,
              const uint8_t *data, size_t len)
{
    if (bus == NULL || bus->ops == NULL || bus->ops->write == NULL) {
        return -1;
    }
    return bus->ops->write(bus, addr, data, len);
}
```

这里有两层结构：`struct i2c_bus` 表示一个具体总线实例，`struct i2c_ops` 是一组操作函数指针（常被称为 operations/vtable）。不同芯片或软件模拟实现只需提供不同的 `i2c_ops`，上层仍调用统一的 `i2c_write()`。

传入 `bus` 本身是关键：同一套 `write` 函数可以通过它拿到寄存器基址、锁、DMA 通道或私有状态，从而支持多个实例；不要把设备状态藏在唯一的全局变量里。

### 5.3 内嵌与指针成员的取舍

| 方式 | 例子 | 优点 | 注意点 |
|---|---|---|---|
| 内嵌结构体 | `struct config cfg;` | 内存连续、生命周期简单、无需额外分配 | 外层对象更大；复制外层会复制成员 |
| 结构体指针 | `struct config *cfg;` | 可共享、可选配、避免复制大对象 | 需判空；必须管理被指向对象生命周期 |
| 操作表指针 | `const struct ops *ops;` | 多实例共享只读函数表，节省 RAM | `ops` 与每个函数指针均需有效 |

---

## 6. 可复述的总结

> 指针函数是“返回指针的函数”，函数指针是“保存函数地址的指针变量”，二者靠括号区分。回调函数是函数指针的典型应用：应用把处理函数和上下文注册给驱动或框架，事件发生时由框架间接调用。嵌入式中要特别说明回调运行在中断还是任务上下文，并保证函数、上下文和数据缓冲区在调用期间有效。多个同类处理函数可以组成函数指针表，用于命令分发或状态机；再把操作表、硬件状态和私有数据放进嵌套结构体，就能做出多实例、可替换实现的驱动接口。

---

## 7. 检查清单

- 函数指针类型是否与实际函数的参数和返回值完全兼容？
- 回调调用前是否检查了函数指针和必要的上下文指针？
- 回调运行在 ISR、任务还是调用者线程？其中能否阻塞、加锁、调用 RTOS API？
- `user_data`、设备对象和接收缓冲区在回调执行时是否仍有效？
- 注销回调、停止 DMA 或销毁对象时，是否避免了并发中的“已注销但仍在调用”？
- 函数指针表的索引或查找结果是否做了范围和空项检查？
