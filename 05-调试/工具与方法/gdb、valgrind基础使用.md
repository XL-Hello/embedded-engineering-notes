# gdb、valgrind 基础使用

## 1. 使用目标

在 Linux 环境下，`gdb` 和 `valgrind` 是排查 C/C++ 程序问题的常用工具：`gdb` 用于定位崩溃、死循环、变量异常、调用栈问题；`valgrind` 用于检查内存泄漏、越界访问、未初始化内存、重复释放等内存问题。

本文重点掌握两个能力：用 `gdb` 打印异常现场信息；用 `valgrind` 输出并分析内存信息。

## 2. 调试前的编译准备

为了让 `gdb` 显示源码行号、函数名和变量信息，编译时加 `-g`；调试阶段建议关闭优化 `-O0`，避免变量被优化掉。

```bash
gcc -g -O0 -Wall main.c -o main
gcc -g -O0 -Wall main.c test.c module.c -o app
g++ -g -O0 -Wall main.cpp -o main
```

| 参数 | 作用 |
| --- | --- |
| `-g` | 生成调试信息 |
| `-O0` | 关闭优化，便于调试 |
| `-Wall` | 打开常见编译警告 |

## 3. gdb 基础使用

### 3.1 启动和运行

```bash
gdb ./main
gdb --args ./main arg1 arg2
```

进入 `gdb` 后运行：`run` 或 `r`；带参数运行：`run arg1 arg2`。

### 3.2 查看崩溃位置

程序段错误时通常会看到：

```text
Program received signal SIGSEGV, Segmentation fault.
```

此时先执行 `bt` 查看调用栈：

```gdb
bt
```

示例：

```text
#0  test_func (p=0x0) at main.c:10
#1  main () at main.c:25
```

含义：`#0` 是当前崩溃位置；`main.c:10` 是崩溃行号；`p=0x0` 表示传入的是空指针。

### 3.3 打印变量和现场信息

| 命令 | 作用 |
| --- | --- |
| `print p` / `p p` | 打印变量 `p` |
| `p ptr` | 查看指针地址 |
| `p *ptr` | 查看指针指向的内容或结构体内容 |
| `p arr[0]` | 查看数组元素 |
| `info locals` | 查看当前栈帧局部变量 |
| `info args` | 查看当前函数参数 |

### 3.4 切换调用栈

当 `bt` 打印多层函数调用时，用 `frame n` 或 `f n` 切换栈帧，再查看当时的参数和局部变量。

```gdb
bt
frame 0
info args
info locals
print 变量名
frame 1
info locals
```

### 3.5 断点和单步

| 命令 | 作用 |
| --- | --- |
| `break main` / `b main` | 在函数入口设置断点 |
| `break main.c:20` | 在指定文件行号设置断点 |
| `continue` / `c` | 继续运行 |
| `next` / `n` | 执行下一行，不进入函数 |
| `step` / `s` | 执行下一行，进入函数 |
| `finish` | 执行到当前函数返回 |
| `list` / `l` | 查看当前源码位置 |
| `list main.c:20` | 查看指定位置源码 |
| `quit` / `q` | 退出 gdb |

## 4. gdb 排查段错误示例

示例代码：

```c
#include <stdio.h>

void test(int *p)
{
    *p = 10;
}

int main(void)
{
    int *ptr = NULL;
    test(ptr);
    return 0;
}
```

编译并调试：

```bash
gcc -g -O0 main.c -o main
gdb ./main
```

`gdb` 中执行：

```gdb
run
bt
frame 0
info args
print p
```

可能输出：

```text
Program received signal SIGSEGV, Segmentation fault.
test (p=0x0) at main.c:5
5       *p = 10;
```

分析：程序在 `main.c:5` 崩溃，`p=0x0` 表示空指针，崩溃原因是对空指针解引用。

面试描述：我会先用 `gcc -g -O0` 编译，再用 `gdb ./程序` 启动，通过 `run` 复现崩溃；崩溃后用 `bt` 看调用栈，定位函数和源码行；再用 `frame`、`info args`、`info locals`、`print` 查看参数和变量，判断是否存在空指针、野指针或数组越界。

## 5. core 文件调试

程序已经崩溃退出时，可以通过 core 文件分析现场。先查看是否开启 core：`ulimit -c`；如果是 `0`，临时开启：`ulimit -c unlimited`。

```bash
ulimit -c unlimited
./main
gdb ./main core
```

进入 `gdb` 后常用：

```gdb
bt
frame 0
info args
info locals
print 变量名
```

core 调试的价值：即使程序已经退出，也能查看崩溃时的调用栈和部分变量现场。

## 6. valgrind 基础使用

安装：

```bash
sudo apt install valgrind      # Ubuntu / Debian
sudo yum install valgrind      # CentOS / RHEL
```

常用命令：

```bash
valgrind ./main
valgrind --leak-check=full ./main
valgrind --leak-check=full --show-leak-kinds=all --track-origins=yes ./main
valgrind --leak-check=full ./main arg1 arg2
valgrind --leak-check=full --log-file=valgrind.log ./main
```

| 参数 | 作用 |
| --- | --- |
| `--leak-check=full` | 详细检查内存泄漏 |
| `--show-leak-kinds=all` | 显示所有类型的泄漏 |
| `--track-origins=yes` | 追踪未初始化值来源 |
| `--log-file=valgrind.log` | 输出结果到日志文件 |

## 7. valgrind 常见输出分析

### 7.1 内存泄漏

示例代码：

```c
#include <stdlib.h>

int main(void)
{
    int *p = malloc(sizeof(int) * 10);
    p[0] = 1;
    return 0;
}
```

检查：

```bash
gcc -g -O0 main.c -o main
valgrind --leak-check=full ./main
```

典型输出：

```text
HEAP SUMMARY:
    in use at exit: 40 bytes in 1 blocks
  total heap usage: 1 allocs, 0 frees, 40 bytes allocated

40 bytes in 1 blocks are definitely lost in loss record 1 of 1
    at 0x...: malloc
    by 0x...: main (main.c:5)

LEAK SUMMARY:
   definitely lost: 40 bytes in 1 blocks
```

重点看：`in use at exit` 表示程序退出时仍未释放的堆内存；`total heap usage` 表示申请和释放次数；`definitely lost` 通常就是明确泄漏；`main.c:5` 是内存申请位置。修复方式：补充 `free(p);`。

### 7.2 越界访问

示例代码：

```c
#include <stdlib.h>

int main(void)
{
    int *p = malloc(sizeof(int) * 10);
    p[10] = 100;
    free(p);
    return 0;
}
```

`p[10]` 越界，因为合法下标是 `0` 到 `9`。valgrind 可能输出：

```text
Invalid write of size 4
    at 0x...: main (main.c:6)
Address 0x... is 0 bytes after a block of size 40 alloc'd
    at 0x...: malloc
    by 0x...: main (main.c:5)
```

重点看：`Invalid write` 是非法写；`Invalid read` 是非法读；`main.c:6` 是越界位置；`block of size 40 alloc'd` 表示原本只申请了 40 字节。

### 7.3 使用未初始化内存

示例代码：

```c
#include <stdio.h>

int main(void)
{
    int a;
    if (a > 0) {
        printf("a > 0\n");
    }
    return 0;
}
```

典型输出：

```text
Conditional jump or move depends on uninitialised value(s)
    at 0x...: main (main.c:6)
```

含义：条件判断依赖未初始化变量，修复方式是给变量初值，例如 `int a = 0;`。

### 7.4 重复释放

示例代码：

```c
#include <stdlib.h>

int main(void)
{
    int *p = malloc(sizeof(int));
    free(p);
    free(p);
    return 0;
}
```

典型输出：

```text
Invalid free()
    at 0x...: free
    by 0x...: main (main.c:7)
```

含义：同一块堆内存释放了两次；释放后建议 `p = NULL;`，避免误用。

## 8. gdb 和 valgrind 的区别

| 工具 | 主要用途 | 常用场景 |
| --- | --- | --- |
| `gdb` | 动态调试程序运行过程 | 段错误、死循环、变量异常、调用栈分析 |
| `valgrind` | 检查内存问题 | 内存泄漏、越界访问、未初始化内存、重复释放 |

简单理解：程序崩溃优先用 `gdb` 看崩溃位置和调用栈；怀疑内存泄漏或非法内存访问，用 `valgrind` 看内存报告；实际排查中常组合使用，先用 `gdb` 定位崩溃现场，再用 `valgrind` 检查背后的内存问题。

## 9. 常用命令速查

### 9.1 gdb 启动与运行

| 场景 | 命令 | 说明 |
| --- | --- | --- |
| 启动调试 | `gdb ./main` | 调试可执行文件 |
| 带参数启动 | `gdb --args ./main arg1 arg2` | 程序有启动参数时使用 |
| 运行程序 | `run` / `r` | 在 gdb 中启动程序 |
| 继续运行 | `continue` / `c` | 断点后继续执行 |
| 退出 gdb | `quit` / `q` | 结束调试 |

### 9.2 gdb 查看异常现场

| 场景 | 命令 | 说明 |
| --- | --- | --- |
| 查看调用栈 | `bt` | 定位崩溃调用链 |
| 切换栈帧 | `frame n` / `f n` | 查看第 n 层函数现场 |
| 查看参数 | `info args` | 当前函数入参 |
| 查看局部变量 | `info locals` | 当前函数局部变量 |
| 打印变量 | `print var` / `p var` | 查看变量值 |
| 打印指针内容 | `p *ptr` | 查看指针指向的数据 |

### 9.3 gdb 断点与单步

| 场景 | 命令 | 说明 |
| --- | --- | --- |
| 函数断点 | `break main` / `b main` | 在函数入口暂停 |
| 行号断点 | `break file.c:10` | 在指定文件行暂停 |
| 下一行 | `next` / `n` | 不进入函数 |
| 进入函数 | `step` / `s` | 进入函数内部 |
| 跳出函数 | `finish` | 执行到当前函数返回 |
| 查看源码 | `list` / `l` | 显示当前位置源码 |

### 9.4 valgrind 基础命令

| 场景 | 命令 | 说明 |
| --- | --- | --- |
| 基础检查 | `valgrind ./main` | 检查常见内存问题 |
| 检查泄漏 | `valgrind --leak-check=full ./main` | 输出详细泄漏信息 |
| 程序带参数 | `valgrind ./main arg1 arg2` | 被测程序有启动参数 |
| 输出到文件 | `--log-file=valgrind.log` | 作为参数追加到命令中 |

### 9.5 valgrind 常用参数

| 参数 | 作用 |
| --- | --- |
| `--leak-check=full` | 详细检查内存泄漏 |
| `--show-leak-kinds=all` | 显示所有泄漏类型 |
| `--track-origins=yes` | 追踪未初始化值来源 |
| `--log-file=valgrind.log` | 将结果写入日志文件 |

常用组合：

```bash
valgrind --leak-check=full \
         --show-leak-kinds=all \
         --track-origins=yes \
         ./main
```

面试或日常排查时重点记：`gdb` 看 `bt / frame / info / print`；`valgrind` 看 `Invalid read/write` 和 `definitely lost`。

## 10. 面试角度的使用建议

面试中不一定要背很多高级命令，关键是讲清楚排查思路。

### 10.1 被问到“程序段错误怎么定位”

可以回答：我会先用 `gcc -g -O0` 重新编译程序，保留调试信息；然后用 `gdb ./程序` 启动，执行 `run` 复现崩溃；崩溃后通过 `bt` 查看调用栈，定位崩溃函数和源码行号；再用 `frame`、`info locals`、`info args`、`print` 查看局部变量和参数，重点判断是否有空指针、野指针、数组越界、对象生命周期异常等问题。

### 10.2 被问到“内存泄漏怎么排查”

可以回答：我会使用 `valgrind --leak-check=full --show-leak-kinds=all ./程序` 运行程序，查看 `HEAP SUMMARY` 和 `LEAK SUMMARY`；重点关注 `definitely lost`，它通常表示确实存在内存泄漏；然后根据 valgrind 输出的调用栈找到 `malloc`、`calloc`、`new` 等内存申请位置，检查对应路径是否缺少 `free` 或 `delete`。

### 10.3 被问到“gdb 和 valgrind 有什么区别”

可以回答：`gdb` 更适合看程序运行现场，比如崩溃时的调用栈、变量值、断点单步执行；`valgrind` 更适合检查内存问题，比如内存泄漏、越界访问、未初始化内存、重复释放；实际排查时通常会结合使用，先用 `gdb` 确定崩溃点，再用 `valgrind` 检查是否存在内存访问问题。

### 10.4 面试中可以主动补充的点

- 调试版本要带 `-g`，最好关闭优化 `-O0`。
- `gdb` 重点掌握 `run`、`bt`、`frame`、`info locals`、`info args`、`print`。
- `valgrind` 重点看 `Invalid read/write` 和 `definitely lost`。
- 内存泄漏不一定马上崩溃，但长期运行的服务会导致内存持续增长。
- 越界访问、重复释放、使用未初始化变量可能表现为偶现问题，需要结合工具和代码路径分析。

## 11. 实际排查流程总结

### 11.1 程序崩溃

```bash
gcc -g -O0 main.c -o main
gdb ./main
```

```gdb
run
bt
frame 0
info args
info locals
print 变量名
```

排查重点：崩溃在哪个文件哪一行；当前函数参数和局部变量是否异常；指针是否为 `NULL`；数组下标是否越界。

### 11.2 内存泄漏

```bash
gcc -g -O0 main.c -o main
valgrind --leak-check=full --show-leak-kinds=all ./main
```

排查重点：是否有 `definitely lost`；泄漏发生在哪个文件哪一行；是否所有 `malloc/calloc/realloc` 都有对应 `free`；C++ 中是否所有 `new` 都有对应 `delete`。

### 11.3 非法内存访问

```bash
valgrind --leak-check=full --track-origins=yes ./main
```

排查重点：是否有 `Invalid read` 或 `Invalid write`；是否访问了已经释放的内存；是否使用了未初始化变量。

## 12. 记忆口诀

```text
崩溃看 gdb，内存看 valgrind。
gdb 先 run，再 bt，看 frame，打印变量。
valgrind 看 Invalid read/write，再看 definitely lost。
编译先加 -g，调试最好 -O0。
```
