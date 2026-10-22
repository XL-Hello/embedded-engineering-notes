# C++ 核心基础

本文对应 [C++17 学习计划](../C++17学习计划.md)的第一阶段，适合有 C 语言基础、准备使用 C++17 开发 Linux 或 RTOS 应用的读者。

本阶段要解决三个问题：C++ 如何表达数据和操作，类如何约束数据的使用，以及对象在创建、复制和销毁时会发生什么。

文中的 `cpp` 代码块使用 C++17 语法；未注明“完整示例”的代码块都是局部片段，需要放入适当的函数或类中。标注为“伪代码”的部分只用于解释流程，不能直接编译。

## 一、从 C 的数据与函数走向 C++ 的对象

### 1.1 C 与 C++ 的核心差异

C 中常见的做法是用结构体保存状态，再用独立函数操作它：

```c
struct Led {
    int pin;
    int enabled;
};

void led_on(struct Led* led);
void led_off(struct Led* led);
```

C++ 可以把数据和操作放进同一个类型，并控制外部能够访问哪些内容：

```cpp
class Led {
public:
    explicit Led(int pin) : pin_(pin) {}

    void on() { enabled_ = true; }
    void off() { enabled_ = false; }
    bool isOn() const { return enabled_; }

private:
    int pin_;
    bool enabled_ = false;
};
```

这里的 `Led` 是类，描述“一种 LED 应该有哪些数据和操作”；`Led statusLed{13};` 创建的 `statusLed` 是对象，是这个类型的一个具体实例。示例只改变软件状态，实际驱动 GPIO 的操作可以放入 `on()` 和 `off()` 中。

C++ 仍然支持普通函数和结构体，也可以直接操作地址。新增的类、引用、构造和析构等机制，让我们能把使用规则写进类型。C++ 也不完全兼容 C，已有 C 文件不能简单地改后缀就认为迁移完成。

### 1.2 编译模型：声明、定义与链接

C++ 程序通常由多个源文件组成。可以把构建过程理解为：

```text
源文件 + 它包含的头文件
        ↓ 预处理
一个翻译单元
        ↓ 编译、汇编
目标文件
        ↓ 与其他目标文件、库链接
可执行程序或固件
```

- **声明**告诉编译器“这个名字是什么、怎样使用”。例如 `int readValue();`。
- **定义**提供具体内容。例如函数体，或真正定义一个对象。
- **头文件**通常放类型定义、函数声明，以及需要让各翻译单元看到的模板或内联定义。
- **源文件**通常放普通函数和非内联成员函数的定义。

一个最小的拆分方式如下：

```cpp
// sensor.hpp
#ifndef SENSOR_HPP
#define SENSOR_HPP

namespace device {
int readValue();
}

#endif
```

```cpp
// sensor.cpp
#include "sensor.hpp"

namespace device {
int readValue() {
    return 42;
}
}
```

```cpp
// main.cpp
#include "sensor.hpp"

int main() {
    return device::readValue() == 42 ? 0 : 1;
}
```

在安装 GCC 的环境中，可以用 `g++ -std=c++17 -Wall -Wextra sensor.cpp main.cpp -o demo` 编译这个例子。

头文件保护宏防止同一个翻译单元重复包含头文件。它不能解决“多个源文件分别包含头文件，导致普通非内联函数被重复定义”的链接问题。因此不要把普通函数的定义随意放进公共头文件。

### 1.3 命名空间：给名字划分归属

不同模块都可能有 `init()` 或 `read()`。命名空间可以避免这些名字冲突：

```cpp
namespace uart {
void init();
}

namespace spi {
void init();
}

// 在函数中调用：
uart::init();
spi::init();
```

`::` 表示作用域限定，`uart::init` 就是“属于 `uart` 的 `init`”。标准库名字通常位于 `std` 中，例如 `std::string`。

公共头文件中尽量不要写 `using namespace std;`，否则所有包含它的文件都会受到名字引入的影响。

## 二、引用、常量与常用函数语法

### 2.1 引用与指针：别名和地址

引用可以理解为已有对象的另一个名字，指针则是保存地址的对象。

```cpp
int value = 10;
int& ref = value;
int* ptr = &value;

ref = 20;       // 修改 value
*ptr = 30;      // 也修改 value

int other = 50;
ptr = &other;   // 指针可以改为指向 other
ref = other;    // 把 other 的值赋给 value，引用不会改绑
```

| 比较项 | 引用 `T&` | 指针 `T*` |
| --- | --- | --- |
| 初始化 | 普通引用定义时必须绑定对象 | 可以初始化为对象地址或 `nullptr` |
| 改变关联对象 | 绑定后不能改绑 | 可以重新赋值，改变指向 |
| 表示“没有对象” | 没有合法的空引用状态 | 可以使用 `nullptr` |
| 访问对象 | 直接使用引用名 | 通常使用 `*` 或 `->` |
| 生命周期风险 | 可能因原对象销毁而悬空 | 可能为空，也可能悬空 |

用参数类型表达接口意图：

```cpp
void increment(int& value) {
    ++value;  // 必须传入一个对象，并允许修改它
}

void resetIfPresent(int* value) {
    if (value != nullptr) {
        *value = 0;  // 允许调用者不提供对象
    }
}
```

引用不负责延长普通被引用对象的生命周期。例如，函数返回局部变量的引用或指针，调用者拿到的就是悬空引用或悬空指针，不能继续使用。

### 2.2 `const`：通过这个名字不能修改什么

```cpp
const int limit = 100;
int value = 10;

const int* p1 = &value;        // 不能通过 p1 修改 value；p1 可以改指向
int* const p2 = &value;        // p2 不能改指向；可以通过它修改 value
const int* const p3 = &value;  // 两种修改都不允许
```

读指针声明时，可以先判断：`const` 修饰的是被指向的数据，还是指针本身。

`const T&` 常用于只读参数，避免复制整个对象：

```cpp
#include <string>

bool isEmpty(const std::string& text) {
    return text.empty();
}
```

这里调用者不需要复制字符串，函数也不能通过 `text` 修改字符串。对于 `int`、`bool` 等小型类型，直接按值传参通常更清楚。

`const` 限制的是特定访问路径，并不意味着对象一定没有其他可写别名。例如 `p1` 指向的 `value` 仍可通过变量名 `value` 修改。`const` 也不自动提供线程同步。

### 2.3 `constexpr`：可以参与编译期计算

`const` 变量可以在运行时初始化；`constexpr` 变量必须由常量表达式初始化。

```cpp
int readConfig();

const int runtimeLimit = readConfig();  // 值在运行时取得，初始化后不能修改
constexpr int channelCount = 4;         // 编译期就能确定

constexpr int square(int value) {
    return value * value;
}

constexpr int capacity = square(channelCount);  // 编译期计算出 16
```

`constexpr` 函数可以参与编译期求值，但不意味着每次调用都必须在编译期执行。传入运行时数据，并在普通运行时上下文中调用时，它也可以像普通函数一样执行。

**在嵌入式项目中，固定通道数、协议字段长度等适合使用 `constexpr`；**

从 Flash 配置区或外设读取的值通常不能直接作为 `constexpr` 变量的初始化值。

### 2.4 函数重载与默认参数

**重载**允许多个函数使用相同名字，通过参数类型、数量等区分：

```cpp
int add(int a, int b) {
    return a + b;
}

double add(double a, double b) {
    return a + b;
}
```

1、`add(1, 2)` 调用整数版本，`add(1.0, 2.0)` 调用浮点版本。
2、**仅返回类型不同不能构成重载；** 
3、参数混用多种类型时，隐式转换还可能让调用产生歧义。

**默认参数**让调用者省略末尾参数：

```cpp
// 头文件中的声明
void send(int value, int timeoutMs = 100);

// 源文件中的定义：这里不再重复默认值
void send(int value, int timeoutMs) {
    // 发送实现
}

// 调用示例：
// send(7);       等价于 send(7, 100);
// send(7, 500);  显式指定超时时间
```

普通参数列表中的默认参数通常从右向左连续提供。不要设计容易冲突的组合，例如同时提供 `send(int)` 和 `send(int, int = 100)`，这样 `send(7)` 会有歧义。

### 2.5 `inline`：先理解定义规则，再考虑性能

`inline` 函数可以在多个翻译单元中具有符合规则的相同定义，因此常用于头文件中的短函数：

```cpp
inline int clampToZero(int value) {
    return value < 0 ? 0 : value;
}
```

对于通常的公共头文件，应确保各翻译单元看到一致的定义，不要用不同宏把同一个内联函数变成不同实现。

`inline` 不保证编译器把函数体展开到调用点。编译器也可能展开没有标记 `inline` 的函数。它在语言层面的关键作用是定义规则，性能要结合优化结果判断。类定义内部直接定义的成员函数在 C++17 中隐式为内联函数。

### 2.6 `auto` 与 `decltype`：让编译器处理类型

`auto` 根据初始化表达式推导类型，推导后类型就固定，不是运行时动态类型。

```cpp
auto count = 10;       // int
auto ratio = 0.5;      // double

const int value = 7;
auto copy = value;     // int，得到独立副本
auto& ref = value;     // const int&，引用原对象
const auto& view = value;  // const int&，通过它只读访问
```

普通 `auto` 按值推导时通常会去掉顶层 `const` 和引用。如果需要保留引用关系，应明确写出 `&`。

`decltype` 根据表达式取得类型，不需要先创建副本：

```cpp
int value = 10;
decltype(value) copy = value;   // int
decltype((value)) ref = value;  // int&
```

这里有一条需要单独记住的规则：对不加括号的变量名使用 `decltype`，得到变量的声明类型；`(value)` 是左值表达式，因此得到引用类型。初学时优先用 `auto` 简化明显的类型，用 `decltype` 解决确实需要精确表达类型的问题。

### 2.7 `nullptr`：明确表达空指针

```cpp
void select(int channel);
void select(const char* name);

// select(0);        // 选择 int 版本
// select(nullptr);  // 选择指针版本
```

`NULL` 是宏，具体定义依赖实现，可能表现为整数零一类的空指针常量，在重载中容易与整数参数混淆。`nullptr` 有专门的类型 `std::nullptr_t`，可以转换为空指针，适合 C++ 的指针初始化、比较和传参。

## 三、类与对象：把使用规则放进类型

### 3.1 `class`、`struct` 与访问控制

C++ 中的 `class` 和 `struct` 都可以有成员变量、成员函数、构造函数等。它们在这里最主要的区别是默认访问权限：`class` 默认为 `private`，`struct` 默认为 `public`；默认继承权限也分别为私有和公有，继承将在下一阶段学习。

| 访问级别 | 含义 |
| --- | --- |
| `public` | 外部可以通过对象访问的接口 |
| `private` | 类内部及友元可访问的实现细节，外部和派生类不能直接访问 |
| `protected` | 类内部、友元及派生类在相应规则下可访问，普通外部代码不能访问 |

**习惯上，简单的数据集合使用 `struct`；**
**需要维持数据有效性、限制操作方式的类型使用 `class`。**

例如，串口波特率不能随意变成负数。把成员设为私有，再提供检查参数的接口，就能在一个位置维护规则。

### 3.2 成员变量、成员函数与 `this`

每个对象各自保存非静态成员变量；成员函数描述如何操作对象。普通非静态成员函数通过 `this` 指针访问当前对象：

```cpp
class Counter {
public:
    void set(int value) {
        this->value_ = value;
    }

    int get() const {
        return value_;  // 相当于 this->value_
    }

private:
    int value_ = 0;
};
```

对 `Counter a; Counter b;` 调用 `a.set(5);`，修改的是 `a` 的成员，`b` 不受影响。大部分时候可以省略 `this->`，只有需要强调当前对象或消除名字冲突时再写。

### 3.3 成员初始化列表：先把成员构造好

构造函数冒号后面的部分是**成员初始化列表**。它描述成员如何获得初始状态：

```cpp
class Channel {
public:
    Channel(int id, int& sharedErrorCount)
        : id_(id), errorCount_(sharedErrorCount) {}

private:
    const int id_;
    int& errorCount_;
};
```

`const` 成员和引用成员都需要在初始化阶段确定。对于类类型成员，初始化列表还可以直接调用合适的构造函数。

理解构造过程时，可以使用下面的伪代码：

```text
开始构造对象：
    先构造基类部分（如果存在）
    再按成员在类中的声明顺序初始化成员
    最后执行构造函数体
```

**成员的初始化顺序由声明顺序决定，与初始化列表的书写顺序无关。** 因此两处顺序应保持一致；成员依赖另一个成员时，被依赖的成员必须先声明。

普通成员也建议给出明确初值，例如 `int count_ = 0;`，避免依赖未初始化的数据。

### 3.4 `const` 成员函数：承诺只读访问对象状态

```cpp
class Sensor {
public:
    int value() const {
        return value_;
    }

    void update(int value) {
        value_ = value;
    }

private:
    int value_ = 0;
};
```

`value()` 后面的 `const` 表示，函数不能通过当前对象修改普通非静态成员。`const Sensor` 对象可以调用 `value()`，不能调用 `update()`。

这种限制不会自动延伸到指针成员指向的外部对象。例如成员是 `int*` 时，`const` 成员函数仍可能通过该指针修改外部整数。因此设计只读接口时，还要考虑间接访问是否改变了外部状态。

### 3.5 静态成员 `static`：属于整个类型

非静态成员每个对象各有一份；静态数据成员属于类型，不随每个对象各自存一份。

```cpp
class DeviceConfig {
public:
    static int baudRate() {
        return defaultBaudRate_;
    }

private:
    inline static int defaultBaudRate_ = 115200;
};

// 在函数中使用：
// int baud = DeviceConfig::baudRate();
```

静态成员函数没有 `this`，不能直接访问某个对象的非静态成员。这里的 `inline static` 数据成员使用了 C++17 的内联变量机制，允许直接在类内定义；此处先会使用，后续阶段再深入。

共享的静态状态被多个线程同时读写时，需要额外同步，`static` 本身不提供线程安全。

## 四、对象生命周期：创建、复制与销毁

### 4.1 构造与析构分别做什么

**构造函数**负责建立对象的初始状态，与类同名，没有返回类型。**析构函数**在对象生命周期结束时负责清理，名字是在类名前加 `~`，没有返回类型，也没有普通参数。

```cpp
class Session {
public:
    Session() {
        // 建立有效的初始状态
    }

    ~Session() {
        // 清理对象拥有的资源
    }
};
```

对于普通局部对象，离开作用域就会执行析构，不要求手动调用：

```text
伪代码：
进入函数
    创建 session → 执行构造函数
    使用 session
离开它所在的作用域 → 执行析构函数
```

文件描述符、锁、设备句柄和动态内存都可以是对象需要管理的资源。让资源的获取和释放跟随对象生命周期，就是后续 RAII 学习的基础。

### 4.2 拷贝构造与拷贝赋值

两者最重要的区别是：目标对象是否已经存在。

```cpp
struct Sample {
    int value = 0;
};

Sample first{10};
Sample second = first;  // 拷贝构造：创建一个新对象
Sample third;
third = first;          // 拷贝赋值：修改一个已经存在的对象
```

对于这个只包含整数的类型，编译器生成的复制操作就能正确工作。

需要自行定义时，典型声明形式如下：

```cpp
class Buffer {
public:
    Buffer(const Buffer& other);             // 拷贝构造
    Buffer& operator=(const Buffer& other);  // 拷贝赋值
};
```

编译器生成的复制通常逐个复制基类和非静态成员。整数成员复制数值，类类型成员使用自己的复制操作；裸指针成员复制地址，不会自动复制地址指向的数据。

后续阶段还会学习移动操作和拷贝消除。因此不要认为所有看起来像复制的语法都一定发生一次实际拷贝。

### 4.3 浅拷贝、深拷贝与所有权

假设对象拥有一块动态缓冲区，其析构函数负责释放它。如果只复制指针，就可能出现两个对象都认为自己拥有同一块内存。

```text
伪代码：浅拷贝一个拥有资源的对象
    A.data → 缓冲区 X
    复制 A 的指针给 B
    B.data → 同一块缓冲区 X

    销毁 A → 释放 X
    使用 B.data → 访问已经释放的内存
    销毁 B → 可能再次释放 X
```

深拷贝则为目标对象建立独立资源：

```text
伪代码：深拷贝
    为 B 分配与 A 等长的新缓冲区 Y
    把 A 缓冲区的内容复制到 Y
    B.data 指向 Y
    A 和 B 分别释放各自的缓冲区
```

浅拷贝本身并非总是错误。如果指针仅用于观察外部对象，且外部对象活得足够久，复制地址可能正是需要的行为。问题在于：**谁拥有资源、谁负责释放，必须明确。**

设计资源类型时，常见选择有独立复制资源、禁止复制，或采用明确的共享所有权。现阶段优先使用 `std::string`、`std::vector` 等已经管理好资源的成员，减少手写内存管理；这些类型会在 STL 阶段深入学习。

### 4.4 创建与销毁顺序

同一作用域内，局部对象按执行到定义语句的顺序构造，在正常离开作用域时按相反顺序析构：

```text
伪代码：
外层作用域：
    创建 A
    内层作用域：
        创建 B
        创建 C
    离开内层 → 销毁 C，再销毁 B
离开外层 → 销毁 A
```

对于包含成员对象的类，构造时先初始化成员，再执行外层对象的构造函数体；销毁时先执行外层对象的析构函数体，再按成员声明的相反顺序销毁成员。数组元素按下标递增顺序构造，按相反顺序销毁。

如果资源 B 依赖资源 A，通常应先建立 A，再建立 B，让清理顺序自然变成先清理 B，再清理 A。

### 4.5 栈对象、堆对象与静态对象

“栈对象”和“堆对象”是工程中常用的说法。理解生命周期时，更准确的分类是自动存储期、动态存储期和静态存储期。

| 类型 | 典型写法 | 生命周期与清理方式 |
| --- | --- | --- |
| 普通局部对象 | 函数中的 `Sensor sensor;` | 通常在执行到定义时构造，离开作用域时自动析构 |
| 动态对象 | `Sensor* p = new Sensor{};` | 成功创建后持续存在，直到通过匹配的方式销毁 |
| 静态对象 | 命名空间作用域对象，或局部 `static Sensor sensor;` | 静态存储持续整个程序；构造时机依初始化形式而定，正常退出时销毁已构造对象 |

局部静态对象需要动态初始化时，在控制流第一次经过其声明时初始化。不同源文件之间的非局部静态对象，其动态初始化依赖不能随意假定顺序。

特别注意：函数中定义的指针变量 `p` 可以是自动存储期对象，而 `new` 创建的 `Sensor` 是动态对象。`p` 离开作用域，并不会自动对它指向的对象执行 `delete`。

RTOS 固件常常长期运行而不正常退出，不能把必须及时释放的资源寄托在程序结束时执行的静态对象析构上。

### 4.6 `new/delete` 与 `malloc/free`

| 比较项 | `new/delete` | `malloc/free` |
| --- | --- | --- |
| 基本工作 | 分配存储并初始化对象；销毁对象并释放存储 | 分配和释放原始存储 |
| 构造、析构 | 普通 `new T` 调用所需构造，`delete` 调用所需析构 | 不自动调用 C++ 构造、析构 |
| 类型 | `new T` 返回 `T*` | `malloc` 返回 `void*` |
| 常规分配失败 | 普通抛异常的 `new` 抛出 `std::bad_alloc` | 返回空指针 |
| 配对要求 | `new` 配 `delete`，`new[]` 配 `delete[]` | `malloc/calloc/realloc` 得到的相应存储配 `free` |

```cpp
Sensor* sensor = new Sensor{};
sensor->update(10);
delete sensor;
sensor = nullptr;

int* samples = new int[8]{};  // 8 个元素均初始化为 0
delete[] samples;
samples = nullptr;
```

混用 `new/free`、`malloc/delete` 或混用单对象与数组的释放方式，都会导致未定义行为。`delete nullptr` 是安全的，但重复删除同一块资源不安全。把一个指针置空也不会修复其他指向同一对象的悬空指针。

`new int;` 与 `new int{};` 也不同：前者创建的整数没有确定的初始值，后者初始化为 0。声明普通局部整数时，也应主动初始化。

上述失败行为针对常规支持异常的 C++ 环境；禁用异常的嵌入式工具链需要按项目配置确认分配失败的处理方式。`std::nothrow` 形式也属于另一种分配接口，后续再展开。

## 五、完整示例：一个有状态约束的串口对象

下面的单文件示例可以作为 C++17 程序编译运行。它只模拟串口状态，不调用真实硬件接口。

```cpp
#include <cassert>

namespace device {

class Uart {
public:
    explicit Uart(int port) : port_(port) {}

    bool open(int baudRate = 115200) {
        if (port_ < 0 || baudRate <= 0 || opened_) {
            return false;
        }

        // 真实项目：先调用驱动，成功后再更新成员状态。
        baudRate_ = baudRate;
        opened_ = true;
        return true;
    }

    void close() {
        if (opened_) {
            // 真实项目：释放该对象拥有的串口资源。
            opened_ = false;
        }
    }

    bool isOpen() const {
        return opened_;
    }

    int baudRate() const {
        return baudRate_;
    }

    ~Uart() {
        close();
    }

    // 禁止复制，避免未来接入真实句柄后重复释放同一资源。
    Uart(const Uart&) = delete;
    Uart& operator=(const Uart&) = delete;

private:
    const int port_;
    int baudRate_ = 0;
    bool opened_ = false;
};

}  // namespace device

int main() {
    device::Uart uart{1};
    assert(!uart.isOpen());

    // 在 assert 外执行操作，避免关闭断言后操作也被移除。
    const bool opened = uart.open();
    if (!opened) {
        return 1;
    }

    assert(uart.isOpen());
    assert(uart.baudRate() == 115200);

    const device::Uart& view = uart;
    assert(view.isOpen());

    uart.close();
    assert(!uart.isOpen());
    return 0;  // 自动析构；再次 close() 不会重复执行释放动作
}
```

这个例子把前面的知识连在一起：命名空间区分模块，私有成员保护状态，初始化列表设置端口，默认参数简化调用，`const` 成员函数提供查询，析构函数负责清理。

其中 `explicit` 用于阻止不希望发生的隐式类型转换；`= delete` 表示禁止对应操作。此处只需知道它们的用途，后续阶段再深入。真实串口类还需要约定打开失败、关闭失败以及多线程访问的处理方式。

## 六、练习与自查

建议按下面的顺序练习，每完成一步都能说明“数据由谁修改、对象何时销毁”。

| 练习 | 要做的事情 | 检查点 |
| --- | --- | --- |
| 引用与指针 | 分别用引用参数和指针参数修改整数 | 能解释引用赋值为何不会改绑；能处理空指针 |
| 常量与推导 | 组合使用 `const`、`auto`、`auto&` | 能说明变量是副本还是引用、是否允许修改 |
| 类与封装 | 编写 `Counter`，提供增加、清零和只读查询接口 | 外部不能直接修改私有成员，初始值明确 |
| 生命周期 | 给一个小类的构造、析构添加日志，创建嵌套局部对象 | 能在运行前预测构造和析构顺序 |
| 复制语义 | 用只含整数的类型分别执行拷贝构造和拷贝赋值 | 能判断目标对象是否已经存在 |
| 资源所有权 | 画出两个裸指针指向同一缓冲区的关系 | 能说明谁释放资源，为什么会出现悬空或重复释放 |
| 综合练习 | 给上面的串口示例增加参数校验和查询接口 | 操作失败时不破坏原状态，查询函数使用 `const` |

完成本阶段后，应能独立回答这些问题：

1. 声明和定义有什么区别？为什么把普通函数定义放入公共头文件可能导致重复定义？
2. 什么情况下选择 `T&`、`const T&` 或 `T*`？如何避免引用或指针悬空？
3. `const` 与 `constexpr` 分别约束什么？`auto` 什么时候会丢掉引用关系？
4. 为什么成员初始化列表先于构造函数体执行？初始化顺序由什么决定？
5. 拷贝构造和拷贝赋值分别在什么时候发生？裸指针被复制时复制的是什么？
6. 普通局部对象、动态对象和静态对象分别由谁触发销毁？
7. 为什么资源类型需要明确复制规则？为什么 `malloc` 不能直接代替普通 `new` 来构造类对象？

当你能清楚解释这些问题，就具备了下一阶段学习继承、多态、RAII 和资源管理规则所需的基础。
