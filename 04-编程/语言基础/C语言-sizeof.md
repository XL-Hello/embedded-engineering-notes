# C 语言 sizeof

> `sizeof` 考的不是死记“某类型几个字节”，而是类型、数组退化、结构体对齐、表达式求值和目标 ABI。面试回答时，应先说明哪些结论由语言保证，哪些必须以当前编译器与目标平台为准。

---

## 1. sizeof 是什么

`sizeof` 是 C 语言运算符，用于得到一个对象或类型占用的字节数；结果类型是 `size_t`，即无符号整数类型。

```c
int x = 0;
printf("%zu\n", sizeof x);       /* 对象形式，括号可省 */
printf("%zu\n", sizeof(int));    /* 类型形式，类型名必须加括号 */
```

这里的“字节”是 C 的 `char` 单位：`sizeof(char)` 永远为 `1`。它不必然等于 8 位；真实位数由 `CHAR_BIT` 给出，常见平台上 `CHAR_BIT == 8`。

```c
#include <limits.h>
printf("CHAR_BIT = %d\n", CHAR_BIT);
```

### 1.1 两种写法

| 写法 | 例子 | 说明 |
|---|---|---|
| 对象/表达式形式 | `sizeof x`、`sizeof(x + y)` | 由表达式的类型决定大小 |
| 类型形式 | `sizeof(int)`、`sizeof(struct packet)` | 直接查询该类型大小 |

对于普通非 VLA 表达式，`sizeof` 在编译期即可确定，表达式通常**不会被执行**。它得到的是大小，不是元素数量、不是字符串长度，也不是动态分配块的容量。

---

## 2. 基础类型：哪些能确定，哪些不能死记

C 标准保证的主要是相对关系与最小范围，例如：

```text
sizeof(char) == 1
sizeof(char) <= sizeof(short) <= sizeof(int) <= sizeof(long) <= sizeof(long long)
```

但 `int` 是否 4 字节、`long` 是否 4/8 字节、指针是否 4/8 字节，均取决于目标平台、编译器和 ABI。嵌入式项目要以实际工具链为准。

常见但不可当作标准保证的情况：

| 类型 | 典型 32 位 MCU | 常见 64 位 Linux（LP64） | Windows 64 位（LLP64） |
|---|---:|---:|---:|
| `char` | 1 | 1 | 1 |
| `short` | 2 | 2 | 2 |
| `int` | 4 | 4 | 4 |
| `long` | 4 | 8 | 4 |
| `long long` | 8 | 8 | 8 |
| 对象指针 | 4 | 8 | 8 |

不要用 `long` 假设“足够放指针”。保存地址请用 `uintptr_t`（若平台提供），打印 `size_t` 用 `%zu`，打印指针用 `%p` 并传 `(void *)p`。

---

## 3. 数组：最常考的 `sizeof` 场景

数组在定义处是真正的数组对象，因此 `sizeof` 返回整个数组大小：

```c
int a[10];
size_t bytes = sizeof(a);              /* 10 * sizeof(int) */
size_t count = sizeof(a) / sizeof(a[0]); /* 10 */
```

推荐宏（仅可用于真正数组）：

```c
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
```

### 3.1 传进函数后，数组退化为指针

```c
void print_array(int a[])
{
    printf("%zu\n", sizeof(a)); /* 实际是 sizeof(int *)，不是数组总大小 */
}
```

形参 `int a[]` 会调整为 `int *a`，数组长度信息已丢失；因此必须额外传长度：

```c
void print_array(const int *a, size_t count);
```

这也是面试陷阱题的标准答案：`sizeof` 能在**数组定义作用域**求总大小，不能在普通函数形参中恢复调用者数组长度。

### 3.2 字符数组与字符串

```c
char s1[] = "abc";
char *s2 = "abc";

sizeof(s1);  /* 4：'a'、'b'、'c'、'\0' */
sizeof(s2);  /* 指针大小：32 位通常 4，64 位通常 8 */
strlen(s1);  /* 3：不包含结尾 '\0' */
```

`sizeof` 不会扫描字符串内容，`strlen` 才会逐字节查找 `\0`。若缓冲区未正确终止，`strlen` 可能越界读取；而 `sizeof` 对数组仍然安全、固定。

---

## 4. 指针与动态内存：sizeof 不知道“指向多大”

```c
int *p = malloc(100 * sizeof(*p));
sizeof(p);      /* 仅 p 这个指针变量大小 */
sizeof(*p);     /* 一个 int 的大小 */
```

无论 `p` 指向 1 个元素还是 1000 个元素，`sizeof(p)` 都只反映地址变量本身。C 标准没有通用接口可从裸指针安全地得知 `malloc` 块大小；应自行保存长度：

```c
struct buffer {
    uint8_t *data;
    size_t len;
};
```

分配时推荐写法：

```c
int *p = malloc(count * sizeof(*p));
```

它随 `p` 的类型变化而变化，避免把 `sizeof(int)` 写错成其他类型。还应检查乘法溢出与 `malloc` 返回值。

---

## 5. 结构体：成员相加为什么常常不对

结构体大小由成员、各成员的对齐要求和尾部填充共同决定。编译器通常插入 padding，使每个成员处于适合自身类型访问的地址，并使数组中的下一个结构体也对齐。

```c
struct A {
    char  c;
    int   i;
    short s;
};
```

常见 32/64 位 ABI 下：`c` 位于偏移 0；为让 `i` 按 4 字节对齐，向后填充3；`i` 位于 4至7，`s` 位于 8至9；末尾再填充至整体对齐倍数，故 `sizeof(struct A)` 常为 12，而不是 1 + 4 + 2 = 7。

```text
偏移： 0     1~3      4~7      8~9    10~11
内容： c   padding      i         s    tail padding
```

### 5.1 成员顺序能减少空间

将对齐要求大的成员放在前面，通常能减少中间填充：

```c
struct bad  { char c; int i; short s; }; /* 常见 12 */
struct good { int i; short s; char c; }; /* 常见 8  */
```

但不能仅凭猜测决定通信协议或 Flash 数据布局；应在目标工具链上用 `sizeof`、`offsetof` 验证。

### 5.2 packed 不是万能省空间方案

`__attribute__((packed))`、`#pragma pack` 可压缩填充，但它们多为编译器扩展。未对齐成员访问可能变慢、触发 HardFault，或生成额外访问指令。协议解析更稳妥的做法通常是按字节读写、显式大小端转换，而非把网络字节流直接强转为结构体指针。

最常用的 GCC / Clang 写法是把属性放在结构体定义后：

```c
struct __attribute__((packed)) frame {
    uint8_t  type;
    uint32_t seq;
    uint16_t len;
};

/* 常见结果：sizeof(struct frame) == 7 */
```

也可写为 `struct frame { ... } __attribute__((packed));`。该写法仅影响这个结构体；若编译器不支持该属性，应通过宏统一封装，避免把编译器相关语法散落在业务代码中：

```c
#if defined(__GNUC__) || defined(__clang__)
#define PACKED __attribute__((packed))
#else
#define PACKED
#endif

struct PACKED protocol_header {
    uint8_t cmd;
    uint16_t len;
};
```

`#pragma pack` 的常用写法是成对 `push` / `pop`，把影响范围限制在目标结构体，`1` 表示最大对齐按 1 字节处理：

```c
#pragma pack(push, 1)
struct frame_wire {
    uint8_t  type;
    uint32_t seq;
    uint16_t len;
};
#pragma pack(pop)      /* 必须恢复原来的对齐状态 */
```

`#pragma pack(n)` 中的 `n` 通常是 1、2、4、8、16；它限制成员的最大对齐，而不是保证所有结构体都恰好没有填充。不要只写 `#pragma pack(1)` 而不恢复，否则会悄悄影响后续所有结构体布局。

若协议、Bootloader 镜像或 Flash 存储格式确实要求固定布局，至少在目标工具链上验证：

```c
_Static_assert(sizeof(struct frame_wire) == 7, "wire layout mismatch");
```

即使大小正确，也仍需处理大小端、未对齐访问和输入缓冲区长度；`packed` 解决的是布局填充，不会自动解决这些问题。

### 5.3 联合体的 sizeof

联合体所有成员共用同一片存储，其大小至少容纳最大成员，还可能为了整体对齐而增大：

```c
union U { uint8_t b; uint32_t w; };
/* sizeof(union U) 常为 4 */
```

---

## 6. 表达式：sizeof 会不会执行 `i++`？

普通情况不会：

```c
int i = 1;
size_t n = sizeof(i++);
/* n == sizeof(int)，i 仍为 1 */
```

因为 `sizeof` 只需知道表达式的类型。然而有一个重要例外：**变长数组（VLA）**的大小在运行期确定，相关表达式可能被求值。

```c
int n = 3;
int a[n];                 /* VLA（取决于编译器/语言标准选项） */
size_t bytes = sizeof(a); /* 运行期得到 3 * sizeof(int) */
```

因此面试中不能绝对说“`sizeof` 永不执行表达式”，正确说法是：对非 VLA 类型，操作数通常不求值；VLA 相关场景需要运行期计算，可能触发求值。

`sizeof` 的操作数也不能是函数类型、不完整类型或位域：

```c
/* sizeof(function_name);  错：函数类型没有对象大小 */
/* struct forward; sizeof(struct forward); 错：不完整类型 */
```

---

## 7. 指针、数组、二维数组的连环题

```c
int a[3][4];
```

| 表达式 | 类型要点 | 大小 |
|---|---|---|
| `sizeof(a)` | 整个二维数组 | `3 * 4 * sizeof(int)` |
| `sizeof(a[0])` | 第一行，是 `int[4]` | `4 * sizeof(int)` |
| `sizeof(a[0][0])` | 单个元素 | `sizeof(int)` |
| `sizeof(a + 0)` | 指向一行的指针 | `sizeof(int (*)[4])` |
| `sizeof(*a)` | 一行数组 | `4 * sizeof(int)` |

二维数组行数可以通过 `sizeof(a) / sizeof(a[0])` 得到，列数可以通过 `sizeof(a[0]) / sizeof(a[0][0])` 得到；前提仍是 `a` 在当前作用域是真实数组。

---

## 8. 嵌入式开发中的实际用法

### 8.1 缓冲区与协议帧

```c
uint8_t tx_buf[64];
uart_send(tx_buf, sizeof(tx_buf));
```

对于定长本地缓冲区，`sizeof(tx_buf)` 比手写 64 更不易失配。若把缓冲区传入函数，应同时传长度。

### 8.2 寄存器和外设结构体

寄存器映射结构体尤其要注意编译器布局、对齐和保留字段。不要仅因 `sizeof` 看起来正确就认定偏移正确；结合 `offsetof(type, member)`、芯片手册和静态断言验证。

```c
#include <stddef.h>
_Static_assert(offsetof(struct regs, CTRL) == 0x10, "CTRL offset mismatch");
```

### 8.3 `size_t`、长度与截断

`sizeof` 返回 `size_t`，它常比 `int` 宽。循环、长度和内存接口优先使用 `size_t`；把它塞进较小的 `uint16_t`/`int` 前应确认范围，避免大缓冲区截断。

---

## 9. 面试高频题与标准回答

### 9.1 `sizeof(char)` 为什么永远是 1？那 char 一定是 8 位吗？

`sizeof` 的单位就是 C 的一个字节，标准定义 `char` 占一个字节，所以结果永远为 1。一个字节包含多少 bit 由 `CHAR_BIT` 决定，主流 MCU/PC 是 8，但标准不强制。

### 9.2 `sizeof` 和 `strlen` 的区别？

`sizeof` 是编译器根据类型/对象得到的存储大小，数组时包含字符串结尾 `\0`；`strlen` 是运行期扫描字符串直到 `\0` 的字符数，不含 `\0`，只适用于有效的以零结尾字符串。指针指向字符串时，`sizeof(pointer)` 仍只是指针大小。

### 9.3 为什么函数内 `sizeof(arr)` 得不到数组长度？

数组作为形参会调整为指针，函数收到的只是首元素地址，没有边界信息。因此 `sizeof(arr)` 等于指针大小。正确接口要额外传 `size_t count`，或传入包含 data 和 len 的结构体。

### 9.4 `sizeof` 是函数吗？为什么有时不加括号？

它是运算符，不是函数。操作数为表达式时可写 `sizeof x` 或 `sizeof(x)`；操作数为类型名时必须写 `sizeof(type)`，因为编译器需要用括号区分类型与表达式。

### 9.5 `sizeof(i++)` 后 i 会变吗？

通常不变：非 VLA 情况下 `sizeof` 只用表达式类型，不执行 `i++`。但 VLA 的大小运行期确定，相关表达式可能求值；严谨回答应补充这个例外。

### 9.6 `sizeof(struct)` 如何计算？

不能只加成员大小。要按成员顺序考虑每个成员的对齐填充，再考虑尾部填充以满足结构体整体对齐；具体规则由 ABI/编译器决定。最可靠的方法是在目标平台用 `sizeof` 和 `offsetof` 验证。

### 9.7 32 位系统上所有指针都一定是 4 字节吗？

常见平坦地址模型中对象指针通常是 4 字节，但语言标准不把“系统位数”直接等同于所有指针类型大小。应以当前 ABI 和 `sizeof(void *)`/实际指针类型的结果为准；函数指针与对象指针也不应假设可互相转换。

### 9.8 `sizeof(void)`、`sizeof(void *)`、`sizeof(function)` 分别怎样？

`void` 是不完整类型，不能对其使用 `sizeof`；`void *` 是对象指针类型，可以，结果为指针大小；函数类型不是对象类型，不能直接 `sizeof(function_name)`。函数指针可以取 `sizeof`，但大小平台相关。

### 9.9 为什么 `malloc(n * sizeof(int))` 常写成 `malloc(n * sizeof *p)`？

后者与 p 的实际指向类型绑定，改变量类型时无需同步修改类型名，减少复制粘贴错误。前提是 p 的声明正确；同时要检查 `n * sizeof *p` 是否溢出和返回值是否为 `NULL`。

### 9.10 如何写一个可靠的数组元素计数宏？它有什么限制？

`#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))`。仅适用于当前作用域的真实数组，传入指针或函数形参会得到错误结果。工程中可配合编译器扩展/静态检查防止误用，但接口设计上更应显式传长度。

---

## 10. 一页速记

```text
sizeof 返回 size_t，单位是 char，sizeof(char) 恒为 1
数组：sizeof(a) 是总字节数；进入函数后 a 变成指针
指针：sizeof(p) 只看地址变量，永远不知道 p 指向的块有多大
字符串：sizeof("abc") == 4；strlen("abc") == 3
结构体：成员大小 + 对齐填充 + 尾部填充，必须目标平台验证
表达式：非 VLA 通常不执行；VLA 是例外
不要背“long/指针固定几字节”，先看 ABI，再用 sizeof 验证
```

面试答题顺序：**先给结论 → 说明前提（数组作用域/平台 ABI）→ 给最小代码例子 → 点出一个陷阱或工程做法**。
