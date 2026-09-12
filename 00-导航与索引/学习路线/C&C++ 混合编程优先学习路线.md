# C/C++ 混编避坑指南：能链接不等于能安全运行

> 目标：让已经能写 C 的嵌入式开发者，安全地把 C++ 引入现有工程，并能看懂、编写和排查 C/C++ 边界代码。
>
> 核心结论：**C 与 C++ 可以在同一工程中共存，但它们的边界必须是稳定的 C ABI 和清晰的资源所有权；不要依赖“头文件能包含”就认为二进制一定能链接或对象一定能安全使用。**

## 1. 先建立正确的全局模型

混合编程不是把 `.c` 改成 `.cpp`，也不是在 C 文件中直接调用 C++ 类。它至少涉及三层边界：

```text
源代码层：C 语法 <-> C++ 语法
编译链接层：C 编译器 / C++ 编译器 <-> 符号名、运行时和链接器
运行时层：C 的显式资源管理 <-> C++ 的构造、析构、异常和 RAII
```

最稳妥的工程结构是：底层驱动、RTOS、厂商 SDK 继续保持 C；在上层新建 C++ 模块；两侧只通过 **C 风格接口**交互。

```text
C 驱动 / SDK / RTOS
        │  C API（头文件可被两种语言包含）
        ▼
C++ 业务、算法、协议、状态机模块
        │
        └─必要时再导出 C API 给旧 C 模块调用
```

### 1.1 首要目标不是“用上全部 C++ 特性”

第一阶段只要做到：

- 能用 C++ 编译和链接已有 C 模块。
- 能从 C++ 调用 C 驱动和 SDK。
- 能把一个 C++ 类封装成 C 可调用的句柄接口。
- 能明确每块内存、每个锁和每个外设句柄由谁创建、谁释放。
- 不让异常、STL 容器或 C++ 对象布局泄漏到 C 边界。

模板元编程、复杂继承、协程和大型框架都可以后学。嵌入式项目先追求可控、可调试和可长期维护。

## 2. 推荐学习顺序

| 优先级 | 先学什么 | 为什么必须先学 | 达成标志 |
| --- | --- | --- | --- |
| P0 | 编译、链接与 `extern "C"` | 解决“函数明明实现了却链接不到” | 能解释 C++ 符号修饰，并正确导出 C 接口 |
| P0 | 头文件兼容与 C/C++ 公共类型 | 防止 C 头文件被 C++ 编译器拒绝 | 同一个 API 头可被 `.c` 与 `.cpp` 包含 |
| P0 | 构造/析构、RAII、异常边界 | 防止资源泄漏、异常跨语言边界 | C++ 资源能自动回收，异常不穿透 C 回调 |
| P1 | 不透明句柄（opaque handle） | 让 C 调用 C++ 类而不暴露对象布局 | C 侧只持有句柄，C++ 侧管理真实对象 |
| P1 | 回调、`void *context` 与所有权 | 适配驱动、RTOS、ISR 和 C SDK | 能把 C 回调转发到 C++ 对象 |
| P1 | 构建系统和最终链接器 | 解决 `libstdc++`、启动代码和混编产物问题 | 能在 Make/CMake 中分别编译并用 C++ 链接 |
| P2 | `new/delete`、STL、RTTI、虚函数 | 评估 ROM/RAM、实时性和异常代价 | 能按项目约束选择是否启用 |

学习时按“先打通一条最小调用链，再扩大使用范围”的方式推进：

```text
C++ 调 C 函数
    ↓
C 调 C++ 的简单函数
    ↓
C 调 C++ 类的句柄包装
    ↓
C 回调进入 C++ 对象
    ↓
在目标板上检查启动、内存、异常和析构行为
```

## 3. 第一关：C++ 的编译、链接与名称修饰

### 3.1 为什么 C++ 调 C 函数需要 `extern "C"`

C 不支持函数重载，符号名通常接近函数原名；C++ 为了区分重载、命名空间和成员函数，会把函数名及参数类型等信息编码为链接符号，这称为**名称修饰**（name mangling）。编译后的目标文件除机器指令外还有符号表，链接器只会按其中的符号名匹配“声明处需要什么”和“定义处提供什么”。

```text
C 定义：              int uart_send(const void *, size_t)
C 目标文件：          导出接近 uart_send 的 C 符号（具体拼写因 ABI/平台而异）
C++ 若按普通声明调用：寻找经过 C++ 名称修饰的另一个符号
结果：        undefined reference / unresolved external
```

例如在常见的 Itanium C++ ABI 下，`void foo(int)` 的 C++ 符号可能是 `_Z3fooi`，而 C 实现导出的通常是 `foo`；符号的精确拼写由编译器和 ABI 决定，不应在代码中依赖它。`extern "C"` 的本质是指定 **C 语言链接**：C++ 编译器不再按 C++ 规则修饰该接口的名字，从而让声明和 C 实现使用同一套符号规则。C 调用 C++ 时同理：应在 C++ 定义侧导出 `extern "C"` 接口。

对外提供 C 接口的头文件，应使用下面的兼容模板：

```c
/* uart_port.h */
#ifndef UART_PORT_H
#define UART_PORT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

int uart_init(uint32_t baudrate);
int uart_send(const void *data, size_t length);

#ifdef __cplusplus
}
#endif

#endif
```

含义是：被 C++ 编译器包含时，花括号内的函数采用 C 链接规则；被 C 编译器包含时，预处理器会跳过 `extern "C"`，仍是普通 C 头文件。

### 3.2 `extern "C"` 不会把 C++ 变成 C

它只影响链接名称和链接约定，不会改变函数体仍使用 C++ 编译器编译这一事实。因此下面的接口可以由 C++ 实现，但对 C 侧表现为 C 函数：

```cpp
extern "C" int crc32_calculate(const void *data, size_t length)
{
    return static_cast<int>(calculate_crc32(data, length));
}
```

不要在 `extern "C"` 中声明 C++ 重载函数、类成员函数、模板或带 C++ 专用类型的接口。C ABI 边界应只使用 C 能理解的类型和布局，例如整数、枚举、普通结构体、指针和函数指针。

### 3.3 ABI：能链接不等于可二进制兼容

ABI（Application Binary Interface，应用二进制接口）规定了二进制如何传递参数、返回值、布局对象和命名符号。不同编译器、不同 C++ 标准库、不同编译选项甚至不同版本，C++ ABI 都可能不兼容。

工程规则：

- 模块边界优先使用稳定的 C API，不直接跨库传递 `std::string`、`std::vector`、异常或 C++ 类对象。
- 同一 C++ 库及其调用方应尽量使用同一工具链、相同 ABI 选项和一致的 C++ 标准库。
- 对外发布库时，公开头文件只暴露 C 类型；把 C++ 实现隐藏在 `.cpp` 中。

## 4. 第二关：头文件与语言差异

### 4.1 C 头文件要同时接受 C 和 C++ 编译器

检查现有 C 头文件时，优先处理这些常见问题：

| C 中常见写法 | 在 C++ 中的问题 | 推荐做法 |
| --- | --- | --- |
| `void *p = malloc(n);` | C++ 不允许隐式转为其他对象指针 | C++ 中避免裸 `malloc`；必要时显式转换并配对 `free` |
| `struct device { ... };` 后直接写 `device d;` | C 中通常需要 `struct device` | 公共接口统一写 `struct device`，或在 C 头中 `typedef` |
| 使用 `bool`、`true`、`false` | C99/C++ 头文件来源不同 | C 用 `<stdbool.h>`，公共 API 用固定宽度整数或明确条件 |
| 可变长数组 VLA | C++ 标准不支持 | 使用固定上限、静态缓冲区或受控动态分配 |
| 指定初始化器、复合字面量 | 部分 C 写法不被目标 C++ 标准接受 | 保持在 C 实现文件中，公共头文件避免使用 |
| `NULL` | 在重载场景可能产生歧义 | C++ 实现中用 `nullptr`；C API 仍可接受空指针 |

### 4.2 初始化与 `const` 的差异要尽早适应

C++ 倾向在声明处初始化，并把“不应修改”写进类型：

```cpp
const uint32_t timeout_ms = 100;
Driver driver{port, baudrate};
```

这不是单纯的代码风格。构造函数能保证对象创建后立即满足不变量；`const` 能让编译器帮助发现误修改。对硬件寄存器、DMA 缓冲区和 RTOS 对象仍需区分“软件语义上的只读”与“硬件可能变化”的情况，不能用 `const` 取代并发同步或 `volatile`。

### 4.3 `volatile` 不是线程安全工具

`volatile` 的作用主要是避免编译器把对易变对象的读写随意省略或合并，常用于 MMIO 寄存器、ISR 与主循环之间的简单标志。它不能保证原子性、互斥、Cache 一致性或跨核内存顺序。

```text
硬件寄存器 / 极简单 ISR 标志  -> 可能需要 volatile
任务间共享计数器              -> 原子操作或锁
跨核共享缓冲区                -> 所有权 + 原子/屏障 + Cache 维护（按平台）
```

## 5. 第三关：让 C++ 调用既有 C 代码

这是风险最低的第一步。C 驱动和 SDK 继续用 C 编译；C++ 文件包含其兼容头文件后直接调用。

```cpp
/* app.cpp */
#include "uart_port.h"

void app_start()
{
    static const char message[] = "boot\r\n";

    (void)uart_init(115200U);
    (void)uart_send(message, sizeof(message) - 1U);
}
```

若厂商头文件没有 `extern "C"` 保护，不要立刻修改第三方文件；可在 C++ 侧单独包一层：

```cpp
extern "C" {
#include "vendor_driver.h"
}
```

只有当头文件内容本身能被 C++ 语法接受时，这种包裹才有效。长期维护的自有接口仍应把兼容宏写进原始公共头文件。

## 6. 第四关：让 C 调用 C++ 类

### 6.1 使用不透明句柄，不暴露类定义

C 不能理解 C++ 类、构造函数或成员函数。正确做法是：C 头文件只前置声明一个不透明类型；C++ 源文件把它映射到真实类。

```c
/* motor_service.h：C 与 C++ 都可包含 */
#ifndef MOTOR_SERVICE_H
#define MOTOR_SERVICE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct motor_service motor_service_t;

motor_service_t *motor_service_create(uint32_t pwm_hz);
void motor_service_destroy(motor_service_t *service);
int motor_service_set_speed(motor_service_t *service, int percent);

#ifdef __cplusplus
}
#endif

#endif
```

```cpp
/* motor_service.cpp */
#include "motor_service.h"

class MotorService {
public:
    explicit MotorService(uint32_t pwm_hz) : pwm_hz_(pwm_hz) {}

    int set_speed(int percent)
    {
        if (percent < -100 || percent > 100) {
            return -1;
        }
        return 0;
    }

private:
    uint32_t pwm_hz_;
};

struct motor_service {
    MotorService impl;

    explicit motor_service(uint32_t pwm_hz) : impl(pwm_hz) {}
};

extern "C" motor_service_t *motor_service_create(uint32_t pwm_hz)
{
    try {
        return new motor_service{pwm_hz};
    } catch (...) {
        return nullptr;
    }
}

extern "C" void motor_service_destroy(motor_service_t *service)
{
    delete service;
}

extern "C" int motor_service_set_speed(motor_service_t *service, int percent)
{
    if (service == nullptr) {
        return -1;
    }

    try {
        return service->impl.set_speed(percent);
    } catch (...) {
        return -1;
    }
}
```

C 侧只知道 `motor_service_t *`，不能访问其成员；对象布局、私有数据和实现细节可在 C++ 中自由调整。这个模式可分为三层：`extern "C"` 函数负责参数校验和错误码转换；`struct motor_service` 充当 C 句柄与 C++ 对象的适配层；`MotorService` 承担实际业务逻辑。只要 C API 和目标平台的 C ABI 保持兼容，内部类的成员或实现变化通常不会泄漏给调用方。

`new motor_service{pwm_hz}` 会依次分配存储、调用 `motor_service` 构造函数，再由成员初始化列表构造 `impl`；`delete service` 则按相反方向调用析构函数并释放存储。因此创建与销毁必须成对且由同一模块完成，C 侧不能用 `free()` 释放由 `new` 创建的对象。公共 C 接口还应在边界处捕获 C++ 异常并转换为错误码或空指针，不能让异常进入 C 调用方。

### 6.2 为嵌入式环境调整动态分配策略

上例用 `new` 方便说明边界，但不代表所有固件都应允许堆分配。若项目禁用或限制动态内存，可改为：

- 静态单例：适合唯一设备实例，但要处理初始化顺序和重入。
- 调用方提供存储区：C API 提供 `init(storage, size, ...)`，C++ 在该内存上 placement new。
- 固定对象池：由模块统一申请、复用和回收实例。

无论采用哪种方式，接口必须写清楚对象最大数量、存储归属、初始化时机和销毁要求。

## 7. 第五关：资源管理、RAII 与异常边界

### 7.1 RAII 是 C++ 最值得优先掌握的能力

RAII（Resource Acquisition Is Initialization，资源获取即初始化）指把资源绑定到对象生命周期：构造函数完成初始化或获取，析构函数完成清理或释放；对象离开作用域、`delete` 执行或构造中途失败时，已构造对象都会按规则析构。它避免了在每条 `return` 路径手工补释放操作。

```cpp
class LockGuard {
public:
    explicit LockGuard(SemaphoreHandle_t mutex) : mutex_(mutex)
    {
        xSemaphoreTake(mutex_, portMAX_DELAY);
    }

    ~LockGuard()
    {
        xSemaphoreGive(mutex_);
    }

    LockGuard(const LockGuard &) = delete;
    LockGuard &operator=(const LockGuard &) = delete;

private:
    SemaphoreHandle_t mutex_;
};

void update_config(SemaphoreHandle_t mutex)
{
    LockGuard lock{mutex};
    /* 中途 return 也会自动释放 mutex */
}
```

RAII 适合管理锁、文件描述符、DMA 通道、时钟使能、临时缓冲区和外设会话。成员初始化列表（如 `: mutex_(mutex)`）是在进入构造函数体前直接初始化成员；`explicit` 构造函数可避免整数等参数被意外隐式转换为对象。析构函数应尽量只做确定、无失败、短时间的清理；不要在析构函数中抛异常。

### 7.2 异常绝不能穿过 C 边界

C++ 异常不能传播到 C 调用方，也不能穿过由 C 库发起的回调栈帧；这些位置都是**异常边界**。对可能抛出异常的 C++ 逻辑，边界函数负责捕获并转换为 C 能表达的错误码、空指针、状态位或日志；内部 C++ 函数可继续向上抛出，由最近的边界统一处理。若能静态保证导出的函数及其调用链为 `noexcept`，则不必为了形式额外包一层 `try/catch`，但该承诺必须长期成立。

```cpp
#include <new>

enum service_status {
    SERVICE_OK = 0,
    SERVICE_INVALID_ARGUMENT = -1,
    SERVICE_NO_MEMORY = -2,
    SERVICE_FAILED = -99,
};

extern "C" int service_run(int *result)
{
    if (result == nullptr) {
        return SERVICE_INVALID_ARGUMENT;
    }

    try {
        *result = run_cpp_service();
        return SERVICE_OK;
    } catch (const std::bad_alloc &) {
        return SERVICE_NO_MEMORY;
    } catch (...) {
        return SERVICE_FAILED;
    }
}
```

错误码应在公共 C 头文件中定义并记录语义，不能只捕获后“不返回结果”。注册给 C 库的 C++ 回调同样必须在回调入口捕获异常；ISR 回调通常不做复杂日志或恢复，只记录状态并尽快返回。

许多 MCU 项目直接关闭异常和 RTTI（例如 `-fno-exceptions`、`-fno-rtti`）以减小代码体积和控制最坏时延。是否启用应由项目统一决定；关闭异常后，代码不能再依赖 `throw/catch`，边界仍应通过返回值表达失败，`new` 的失败处理方式也要按工具链配置确认。

## 8. 第六关：C 回调如何进入 C++ 对象

C SDK 的回调通常同时给出“事件数据”和一个由调用方原样带回的 `context` 指针：

```c
typedef void (*rx_callback_t)(const uint8_t *data, uint32_t length, void *context);
void uart_register_rx_callback(rx_callback_t callback, void *context);
```

难点在于：C SDK 要的是普通函数指针 `void (*)(...)`，而非静态成员函数还隐含 `this`，类型为 `void (Protocol::*)(...)`，二者不能直接转换。把对象地址作为 `context` 注册，再用静态桥接函数把它转回对象，即可完成转发：

```cpp
class Protocol {
public:
    void start()
    {
        // ① 把“接到数据后调用哪个普通函数”及“当前对象是谁”交给 C SDK。
        uart_register_rx_callback(&Protocol::on_rx_bridge, this);
    }

private:
    // ② 静态成员函数没有隐含 this，可匹配 C 的函数指针类型。
    static void on_rx_bridge(const uint8_t *data, uint32_t length, void *context)
    {
        try {
            // ③ C SDK 原样传回 start() 中登记的 this。
            auto *self = static_cast<Protocol *>(context);
            if (self != nullptr) {
                // ④ 恢复对象后，才进入可访问成员状态的普通成员函数。
                self->on_rx(data, length);
            }
        } catch (...) {
            /* 绝不能重新抛出；按上下文记录错误或置状态位 */
        }
    }

    void on_rx(const uint8_t *data, uint32_t length)
    {
        /* 若来自 ISR，此处只能做 ISR 安全且很短的工作 */
        (void)data;
        (void)length;
    }
};
```

```text
UART 收到数据
    ↓ C SDK 调用 on_rx_bridge(data, length, context)
静态桥接函数
    ↓ context 转回 Protocol *
self->on_rx(data, length)
    ↓ 使用该对象的成员状态处理数据
```

因此 `context` 不是数据缓冲区，而是“本次回调应交给哪个 C++ 对象”的地址。不要改用全局对象指针：它会限制实例数量，并使并发和生命周期更难管理。

必须同时确认：

- 回调来自任务上下文还是 ISR；能否加锁、分配内存、打印日志或调用 RTOS API。
- 注销回调与销毁对象的先后顺序；对象销毁后不得再留下旧 `context`。
- 数据缓冲区在回调返回后是否仍有效；需要异步处理时要复制数据或转移缓冲区所有权。

## 9. 构建系统：分别编译，使用 C++ 驱动最终链接

文件扩展名决定通常的编译语言：`.c` 用 C 编译器，`.cpp/.cc/.cxx` 用 C++ 编译器。不要把所有 C 文件都改为 C++，否则会引入不必要的语法和行为变化。

```make
CC      := arm-none-eabi-gcc
CXX     := arm-none-eabi-g++
CFLAGS  := -std=c11 -Wall -Wextra
CXXFLAGS:= -std=c++17 -Wall -Wextra -fno-exceptions -fno-rtti

main.o: main.c motor_service.h
	$(CC) $(CFLAGS) -c $< -o $@

motor_service.o: motor_service.cpp motor_service.h
	$(CXX) $(CXXFLAGS) -c $< -o $@

firmware.elf: main.o motor_service.o
	$(CXX) $^ -o $@
```

最终链接使用 `g++`（或显式补齐相应 C++ 运行时库），因为它会正确引入 C++ 运行时和标准库依赖。裸机项目还要确认启动文件是否调用全局/静态 C++ 对象的构造函数；仅能成功链接不代表全局对象一定已正确构造。

建议在构建中打开足够严格的告警，并把 C 与 C++ 的编译选项分开管理。尤其注意 CPU 架构、FPU、浮点 ABI、优化级别、结构体对齐和链接脚本必须一致。

## 10. 最小可落地的目录与迁移方式

```text
project/
├── drivers/             # 保持 C：寄存器、厂商 HAL、RTOS 适配
│   ├── uart_port.c
│   └── uart_port.h
├── services/            # 新增 C++：协议、算法、状态机
│   ├── motor_service.cpp
│   └── motor_service.h  # 对 C 导出稳定 API
└── app/
    └── main.c           # 可继续保持 C，调用 service 的 C API
```

推荐迁移步骤：

1. 先选一个无硬实时 ISR、依赖较少的纯逻辑模块，例如协议解析或状态机。
2. 保持该模块对外的 C API 不变，只把内部实现迁到一个 `.cpp` 文件。
3. 为每个导出的 C 函数补齐空指针、参数范围、异常和错误码处理。
4. 在主机单元测试与目标板上分别验证；目标板重点检查启动、栈、堆、Flash/RAM 和实时性。
5. 稳定后再逐个迁移模块，不要在一次提交中同时重构 API、替换构建系统和引入大量 C++ 库。

## 11. 高频错误与排查清单

| 现象 | 常见原因 | 优先检查 |
| --- | --- | --- |
| `undefined reference` / `unresolved external` | C++ 按 C++ 名称找 C 函数，或漏链接目标文件 | 声明是否有 `extern "C"`；最终链接是否包含该对象/库 |
| C++ 不能包含某个 C 头 | 头文件里有 C 专用语法或缺少兼容宏 | 先定位首个编译错误；公共声明移到兼容头 |
| 程序启动即 HardFault | 全局 C++ 对象构造未执行、栈太小、运行时未初始化 | 启动文件、`.init_array`、map 文件和栈水位 |
| C 调 C++ 后崩溃 | 句柄无效、`new/delete` 与 `malloc/free` 混用、对象已销毁 | 创建/销毁配对、空指针检查、所有权记录 |
| 回调偶发野指针 | 对象已销毁但 C SDK 仍保留 `context` | 先注销回调/停止外设，再销毁对象 |
| 代码体积明显增长 | 异常、RTTI、STL、全局构造或隐式运行时库 | 对比 map 文件，按项目策略关闭或替换 |
| ISR 中卡死或断言 | C++ 回调做了阻塞、分配、锁或复杂逻辑 | 确认回调上下文，只通知任务处理 |

调试链接问题时可查看符号表：

```bash
arm-none-eabi-nm -C build/motor_service.o
arm-none-eabi-nm -C build/firmware.elf | grep motor_service
```

`-C` 会把 C++ 修饰后的符号反解为可读形式，便于确认调用方期望的名称与实现方实际导出的名称是否一致。


## 12. 总结

对 C 开发者而言，C++ 混合编程最先要掌握的不是语法糖，而是边界：

1. 用 `extern "C"` 解决 C/C++ 符号链接规则差异。
2. 用可同时被两种语言包含的头文件稳定公共 API。
3. 用不透明句柄把 C++ 类隐藏在 C API 后面。
4. 用 RAII 管理资源，但不让异常跨越 C、回调或 ISR 边界。
5. 用“静态桥接函数 + context”把 C 回调安全转发到 C++ 对象。
6. 分别编译 C 与 C++，并用 C++ 驱动完成最终链接。

只要上述规则稳定，C++ 就能以小范围、可回退的方式逐步进入现有嵌入式工程，而不必一次性重写成熟的 C 驱动和基础设施。
