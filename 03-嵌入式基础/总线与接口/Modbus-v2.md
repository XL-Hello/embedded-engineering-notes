# Modbus RTU 从入门到工程实践

> 面向 Linux + C + libmodbus 的技术科普与工程设计指南

本文从协议分层讲起，解释一笔 Modbus RTU 事务如何在 RS485 总线上完成，然后给出可运行的 libmodbus 示例，最后讨论一主多从场景中的时序、异常、线程模型、稳定性和工程化设计。

阅读后应能回答三个问题：

1. Modbus、Modbus RTU、RS485、UART 和 libmodbus 分别解决什么问题？
2. 为什么“能读到数据”的程序不一定能长期稳定运行？
3. 如何让 16～32 台从机共享一条 RS485 总线，同时做到可恢复、可观测、可维护？

快速导航：

- [第1章：概念与分层](#第1章-modbus-是什么)
- [第2章：RTU 事务、帧与时序](#第2章-一次-modbus-rtu-通信是如何完成的)
- [第3章：Linux + C + libmodbus 最小实战](#第3章-linux--c--libmodbus-最小实战)
- [第4章：时序与异常](#第4章-modbus-rtu-的时序与异常)
- [第5章：一主多从软件架构](#第5章-一主多从-modbus-rtu-软件架构)
- [第6章：稳定性与工程化](#第6章-稳定性与工程化设计)
- [附录 A：要点速查（FAQ）](#附录-a-要点速查faq)
- [附录 B：术语与缩写](#附录-b-术语与缩写)

按目标阅读：

```text
只想先跑通一台设备       → 第1章 1.1/1.3 → 第3章
排查偶发 timeout/CRC     → 第2章 2.8 → 第4章 → 第3章 3.6
设计多设备通信层         → 第5章 → 第6章
上线评审或快速复习       → 第6.8 → 附录 A
```

本文默认场景为：Linux 主机作为 Modbus RTU 主站，一条半双工 RS485 总线连接多台从机，程序使用 C11、pthread 和 libmodbus。本文给出通信层设计契约和关键流程，不提供完整 pthread 队列实现；具体实现以延伸阅读中的项目设计文档为准。文中的初始参数只用于建立可运行基线，最终值必须由真实设备抓包和压力测试确定。

---

## 第1章 Modbus 是什么

### 1.1 先建立整体认知

Modbus 是一种工业通信协议。它定义了通信双方如何组织请求和响应，例如：访问哪台设备、执行什么操作、读取哪个地址、传输多少数据以及如何报告异常。

Modbus 并不规定电压、电缆和接线方式。同一种 Modbus 数据模型可以运行在不同传输方式上：

| 名称 | 主要职责 | 本文中的角色 |
| --- | --- | --- |
| Modbus | 定义功能码、数据模型和请求/响应语义 | 应用层协议 |
| Modbus RTU | 定义串行链路上的二进制帧、CRC 和帧间静默 | 本文使用的协议封装 |
| RS485 | 定义差分电气接口，支持较远距离和多节点 | 物理层 |
| UART | 将字节按波特率、数据位、校验位、停止位串行收发 | 主控侧串口控制器 |
| libmodbus | 封装组帧、CRC、收发和响应校验 | Linux C 通信库 |

可以把它们理解为一条自上而下的数据路径：

```text
业务程序：读取 1 号设备的温度
    ↓
libmodbus：生成地址、功能码、寄存器和 CRC
    ↓
Modbus RTU：形成二进制请求帧
    ↓
UART：按 115200、8N1 等参数发送字节
    ↓
RS485 收发器：把 UART 电平转换为 A/B 差分信号
    ↓
双绞线与从机
```

这里最容易混淆的一点是：**RS485 不等于 Modbus**。RS485 只说明电气接口，设备完全可能在 RS485 上运行厂商私有协议。只有设备手册明确给出 Modbus RTU、从机地址、功能码和寄存器表时，才能直接使用 libmodbus 的标准读写 API。

### 1.2 Modbus RTU 与 Modbus TCP

两者共享功能码和寄存器模型，但链路封装不同：

| 对比项 | Modbus RTU | Modbus TCP |
| --- | --- | --- |
| 常见介质 | UART + RS485 | Ethernet + TCP/IP |
| 帧边界 | 静默时间和帧长度 | TCP 报文中的 MBAP Header |
| 差错检测 | CRC16 | 依赖 TCP/IP 校验，不带 RTU CRC |
| 设备标识 | Slave ID | Unit Identifier |
| 并发特点 | 一条半双工总线严格串行 | 可建立多个 TCP 连接 |

本文只讨论串行链路上的 Modbus RTU。将完整 RTU ADU（含 CRC）原样封装进 TCP 得到的是现场常见的 **RTU over TCP**，并不是标准 Modbus TCP；两者的帧格式、CRC 和 MBAP Header 均不同，客户端必须按网关的实际模式配置。libmodbus 的 `modbus_new_tcp()` 实现标准 Modbus TCP，RTU over TCP 需要额外适配。不要在 RTU 帧中加入 MBAP Header，也不要假设 TCP 网关一定使用标准 Modbus TCP。

### 1.3 UART、RS232 与 RS485 的关系

UART 负责产生和接收串行字节流；RS232、RS485 负责把该字节流转换为不同的电气信号。常见嵌入式链路是：

```text
CPU UART TX/RX ↔ RS485 收发器 ↔ A/B 双绞线
```

RS485 常见为两线半双工，同一时刻只能有一个节点发送。主站发完请求后必须释放发送方向，从机才能响应。USB-RS485 转换器通常自动切换方向；SoC UART 外接 485 收发器时，可能需要驱动或 RTS 控制 DE/RE。

串口参数必须在所有节点上完全一致。例如 `115200 8N1` 表示：

- 波特率 115200 bit/s；
- 8 个数据位；
- 无校验位（None）；
- 1 个停止位。

Modbus 串行规范的默认 RTU 格式是 8E1；无校验时规范使用 2 个停止位，以保持 11 bit 字符。产业现场也常见 8N1，必须以设备手册和实测为准。校验位或停止位的差异会改变字符时间；参数不一致时，常见现象不是“收到明确错误”，而是超时、乱码或 CRC 错误。

### 1.4 libmodbus 做什么，不做什么

libmodbus 在 RTU 模式下可以完成：

- 构造和解析标准 Modbus RTU 帧；
- 自动计算并校验 CRC16；
- 操作 Linux 串口；
- 校验从机地址、功能码、长度和异常响应；
- 提供线圈、离散输入、输入寄存器和保持寄存器 API。

它不会替应用完成：

- 多从机轮询调度和优先级；
- 请求队列、业务 deadline 和过载保护；
- 设备在线状态管理；
- 针对业务语义的安全重试；
- 总线级故障判断、长期指标和告警；
- 寄存器值到温度、电压、状态等业务字段的映射。

因此，libmodbus 是可靠通信层的基础组件，但不是完整的设备管理系统。

### 1.5 一条总线上的核心原则

> 一条 RS485 总线只能有一个通信执行者；所有请求统一排队并串行执行。

对本文场景，可建立如下资源关系：

```text
1 条物理 RS485 总线
    = 1 个串口设备
    = 1 个 modbus_t
    = 1 个 Bus Worker
    → 连接 16～32 个不同 Slave ID 的从机
```

多条物理总线则各自拥有独立的串口、`modbus_t`、请求队列和 Worker。不要为同一条总线上的 32 台从机创建 32 个并发通信线程。

**本章小结：** RS485 管电气，RTU 管帧与时序，Modbus 管语义，libmodbus 管组帧收发；调度、健康、恢复和业务映射由应用负责。一条总线对应一个串口、一个 `modbus_t` 和一个 Worker。

---

## 第2章 一次 Modbus RTU 通信是如何完成的

### 2.1 主从请求—响应模型

传统文档称主站（Master）和从站（Slave），新文档也常称客户端（Client）和服务器（Server）。在串行总线上，其基本行为不变：

1. 主站选择一个从机地址并发送请求；
2. 被点名的从机处理请求并返回响应；
3. 其他从机保持静默；
4. 主站收到完整响应或等待超时后，才能开始下一笔事务。

```text
Master                       Slave 1        Slave 2
  │── ID=1, 读寄存器 ────────►│               │
  │                           │               │
  │◄──────── 响应 ────────────│               │
  │
  │── ID=2, 写寄存器 ────────────────────────►│
  │◄────────────────────────── 响应 ──────────│
```

正常情况下从机不会主动上报，主站也不能同时向两个从机发起事务。地址 0 通常用于广播写：从机执行但不响应。广播无法确认结果，本文的可靠通信架构默认禁用地址 0。

### 2.2 RTU 帧结构

标准 RTU 请求帧由四部分组成：

```text
+------------+-------------+------------------+-------------+
| 从机地址   | 功能码      | 数据             | CRC16       |
| 1 Byte     | 1 Byte      | N Bytes          | 2 Bytes     |
+------------+-------------+------------------+-------------+
```

- 从机地址：通常为 1～247；
- 功能码：说明读、写以及访问的数据区；
- 数据：起始地址、数量或要写入的值；
- CRC16：检测传输过程中是否发生位错误，RTU 帧中低字节先发送。

例如，读取 1 号从机从地址 `0x0000` 开始的 2 个保持寄存器：

```text
请求帧（8 Bytes）

+----------+----------+---------------+----------+----------+
| Slave ID | Function | Start address | Quantity | CRC16    |
+----------+----------+---------------+----------+----------+
| 01       | 03       | 00 00         | 00 02    | C4 0B    |
+----------+----------+---------------+----------+----------+
| 1 Byte   | 1 Byte   | 2 Bytes       | 2 Bytes  | 2 Bytes  |
+----------+----------+---------------+----------+----------+

线上字节流：01 03 00 00 00 02 C4 0B
```

若寄存器值分别为 25 和 100，响应形态为：

```text
响应帧（9 Bytes）

+----------+----------+------------+----------------+----------+
| Slave ID | Function | Byte count | Register data  | CRC16    |
+----------+----------+------------+----------------+----------+
| 01       | 03       | 04         | 00 19  00 64   | 2A 1F    |
+----------+----------+------------+----------------+----------+
| 1 Byte   | 1 Byte   | 1 Byte     | 4 Bytes        | 2 Bytes  |
+----------+----------+------------+----------------+----------+

线上字节流：01 03 04 00 19 00 64 2A 1F
寄存器 0：00 19 = 25
寄存器 1：00 64 = 100
```

libmodbus 的 debug 输出通常会显示方括号分隔的十六进制字节，可直接按以上结构逐项核对。

### 2.3 四类数据对象与常用功能码

Modbus 数据模型包含四个逻辑区：

| 数据区 | 位宽 | 访问属性 | 常用功能码 | libmodbus API |
| --- | ---: | --- | --- | --- |
| Coil（线圈） | 1 bit | 读写 | `0x01`、`0x05`、`0x0F` | `modbus_read_bits`、`modbus_write_bit(s)` |
| Discrete Input（离散输入） | 1 bit | 只读 | `0x02` | `modbus_read_input_bits` |
| Input Register（输入寄存器） | 16 bit | 只读 | `0x04` | `modbus_read_input_registers` |
| Holding Register（保持寄存器） | 16 bit | 读写 | `0x03`、`0x06`、`0x10` | `modbus_read_registers`、`modbus_write_register(s)` |

常用功能码如下：

| 功能码 | 含义 | 请求中的主要参数 |
| ---: | --- | --- |
| `0x01` | 读线圈 | 起始地址、数量 |
| `0x02` | 读离散输入 | 起始地址、数量 |
| `0x03` | 读保持寄存器 | 起始地址、数量 |
| `0x04` | 读输入寄存器 | 起始地址、数量 |
| `0x05` | 写单个线圈 | 地址、`0xFF00` 或 `0x0000` |
| `0x06` | 写单个保持寄存器 | 地址、16 位值 |
| `0x0F` | 写多个线圈 | 起始地址、数量、字节数、值 |
| `0x10` | 写多个保持寄存器 | 起始地址、数量、字节数、值 |

`0x03`/`0x04` 一次最多读 125 个寄存器，`0x10` 最多写 123 个寄存器；位操作中，`0x01`/`0x02` 最多读 2000 位，`0x0F` 最多写 1968 位。它们分别对应 libmodbus 的 `MODBUS_MAX_READ_REGISTERS`、`MODBUS_MAX_WRITE_REGISTERS`、`MODBUS_MAX_READ_BITS` 和 `MODBUS_MAX_WRITE_BITS`。工程代码应在入队前校验数量和 `start_address + quantity <= 0x10000`，不要等到通信线程中才发现参数非法。

本文聚焦上述常用功能码，不展开 `0x16` Mask Write 和 `0x17` Read/Write Multiple；libmodbus 3.1.x 分别提供 `modbus_mask_write_register()` 和 `modbus_write_and_read_registers()`。

### 2.4 寄存器地址不是业务数据

Modbus 寄存器本质上只是 16 位无符号数。设备厂商需要另外定义：

- 哪个地址表示什么业务量；
- 值是否有符号；
- 缩放比例，例如原始值 253 表示 25.3 ℃；
- 32 位整数、浮点数占用几个寄存器；
- 多寄存器数据的字序和字节序；
- 是否只读、是否掉电保存以及写入后的生效时机。

常见手册用 `40001` 表示第一个保持寄存器，但协议帧中的地址通常是从 0 开始的偏移量：

```text
手册写法：40001
PDU 地址：0x0000
libmodbus addr 参数：0
```

也有厂商手册直接给出 0 基或 1 基地址。**不要仅凭 `4xxxx` 机械换算**，应先用厂商示例帧或调试工具验证。地址差 1 是 Modbus 项目最常见的问题之一。

### 2.5 16 位之外的数据与字节序

RTU 报文中单个寄存器按高字节在前传输，但一个 32 位值横跨两个寄存器时，寄存器顺序并没有统一的设备级约定。例如 `0x11223344` 可能表示为：

```text
ABCD：0x1122 0x3344
CDAB：0x3344 0x1122
BADC：0x2211 0x4433
DCBA：0x4433 0x2211
```

libmodbus 提供 `MODBUS_GET_INT32_FROM_INT16`、`modbus_get_float_abcd/badc/cdab/dcba()` 及对应 setter 等转换辅助工具，但它们只解决拼接和字序，不解决符号、缩放或单位。仍须先确认设备手册规定的顺序，并把转换集中在 DeviceManager 的寄存器映射层，不要散落在 UI 或业务代码中。

### 2.6 CRC16 的作用

Modbus RTU 使用 CRC-16/Modbus，初始值为 `0xFFFF`，多项式的反射形式为 `0xA001`。接收方对地址到数据区的全部字节计算 CRC，并与帧尾比较。

CRC 能发现传输错误，但不能纠正错误，也不提供加密、身份认证或防重放能力。libmodbus 已自动生成和校验 CRC，正常业务代码不应再次计算；只有分析裸帧、开发抓包工具或实现私有链路时才需要手算。

### 2.7 正常响应与异常响应

正常响应通常回显原功能码。若从机收到并理解了帧，但无法完成请求，则返回异常帧：

```text
异常功能码 = 原功能码 | 0x80
```

例如请求功能码为 `0x03`，异常响应中的功能码为 `0x83`。紧随其后的异常码说明原因：

| 异常码 | 名称 | 常见含义 |
| ---: | --- | --- |
| `0x01` | Illegal Function | 不支持该功能码 |
| `0x02` | Illegal Data Address | 地址或地址范围非法 |
| `0x03` | Illegal Data Value | 数量或写入值非法 |
| `0x04` | Slave Device Failure | 从机内部处理失败 |
| `0x05` | Acknowledge | 已接受，仍需较长时间处理 |
| `0x06` | Slave Device Busy | 从机忙，可在退避后重试 |

收到合法异常响应恰恰证明设备可达。它是协议或业务错误，不应被误判为设备掉线。

### 2.8 RTU 的时间边界

RTU 没有显式帧头，依赖总线静默识别帧边界。字符时间由串口格式决定：

```text
字符位数 = 1 个起始位 + 数据位 + 可选校验位 + 停止位
字符时间 = 字符位数 / 波特率
```

例如 9600 8N1 每字符为 10 bit，单字符约 `1.042 ms`，3.5 字符约 `3.646 ms`。

规范常用规则为：

- 波特率不高于 19200 bit/s：按 1.5 和 3.5 字符时间计算；
- 波特率高于 19200 bit/s：建议采用固定 `t1.5 = 750 µs`、`t3.5 = 1.750 ms`。

工程上应确保相邻 RTU 帧之间至少保持 `t3.5` 静默。它与“请求超时后等待迟到响应”的 guard interval 不是同一个概念。

`t1.5` 是接收帧内允许的字符间隔上限；libmodbus 的 byte timeout 是应用层的近似对应物，但受操作系统调度和 USB 批量传输影响，不能机械设置为 750 µs。

正常与异常事务的时间关系如下：

```text
正常：主站请求 ┃■■■■┃──从机处理──┃■■■■ 响应┃──t3.5──┃下一帧
                 └──── response_timeout（byte_timeout=0 时覆盖完整响应）────┘
                                      响应帧内相邻字节 ≤ byte_timeout

异常：主站请求 ┃■■■■┃──── response_timeout 耗尽 ────┤ flush
                                                       ├─ guard ─┤ drain ├─t3.5─┤下一帧
                       迟到响应若在 guard 内到达，将与下一笔事务隔离
```

这里的 `t3.5` 是实际帧之后的协议静默要求，guard 是通信异常后的工程隔离手段，byte timeout 约束响应帧内部，三者不可互相替代。

**本章小结：** 一笔事务必须同时满足地址/功能码/数量正确、CRC 正确和时间边界正确；任一项出错都可能表现为 timeout、乱码或坏帧。

---

## 第3章 Linux + C + libmodbus 最小实战

### 3.1 开始前确认清单

写代码前至少确认以下信息：

| 项目 | 示例 |
| --- | --- |
| 协议 | Modbus RTU，而非 RS485 私有协议 |
| 串口 | `/dev/serial/by-id/...` 或 `/dev/ttyUSB0` |
| 串口参数 | 9600、8N1 |
| 从机地址 | 1 |
| 功能码 | `0x03` |
| 协议地址 | `0x0000` |
| 数量 | 2 个寄存器 |
| 典型/最大响应时间 | 由手册和实测确定 |
| 数据解释 | 无符号/有符号、倍率、字序 |

硬件侧还要确认 A/B 线、公共参考地、终端电阻、偏置电阻和收发方向控制方式。长总线优先使用总线型拓扑，避免大规模星形分支。

### 3.2 安装与确认环境

Ubuntu/Debian 可直接安装：

```bash
sudo apt update
sudo apt install libmodbus-dev pkg-config
pkg-config --modversion libmodbus
pkg-config --cflags --libs libmodbus
```

本文工程设计要求 libmodbus `>= 3.1.6`，建议使用 `3.1.10+`。3.0.x 的 `modbus_set_response_timeout()` 接收 `struct timeval *` 且无返回值；从 3.1.0 起改为返回 `int` 并接收秒、微秒两个 `uint32_t` 参数。照抄本文代码到旧版本可能无法编译。

确认 USB 串口：

```bash
dmesg | tail -n 30
ls -l /dev/ttyUSB0
ls -l /dev/serial/by-id/
```

正式部署优先使用 `/dev/serial/by-id/` 或固定 udev 软链接，因为 `/dev/ttyUSB0` 的编号可能在插拔或重启后变化。

Ubuntu/Debian 中串口通常属于 `dialout` 组：

```bash
sudo usermod -aG dialout "$USER"
```

重新登录后组权限生效。正式服务不应依赖 root 身份运行。

### 3.3 一个可运行的最小主站

下面的示例读取 1 号从机的两个保持寄存器。联调示例刻意采用 9600 bit/s 和 500 ms timeout 放宽时序容错，不是多设备项目的量产配置；项目基线见 6.7，最终值仍须实测校准。

```c
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <modbus.h>

int main(void)
{
    modbus_t *ctx = NULL;
    uint16_t regs[2] = {0};
    int rc;
    int exit_code = 1;

    ctx = modbus_new_rtu("/dev/ttyUSB0", 9600, 'N', 8, 1);
    if (ctx == NULL) {
        fprintf(stderr, "modbus_new_rtu failed\n");
        return 1;
    }

    /* 500 ms；tv_usec 必须小于 1000000。 */
    if (modbus_set_response_timeout(ctx, 0, 500000) == -1) {
        fprintf(stderr, "set response timeout failed: %s\n",
                modbus_strerror(errno));
        goto cleanup;
    }

    /* 第一版关闭 byte timeout，由 response timeout 约束整帧。 */
    if (modbus_set_byte_timeout(ctx, 0, 0) == -1) {
        fprintf(stderr, "set byte timeout failed: %s\n",
                modbus_strerror(errno));
        goto cleanup;
    }

    modbus_set_debug(ctx, TRUE); /* 仅联调时启用 */

    if (modbus_connect(ctx) == -1) {
        const int saved_errno = errno;
        fprintf(stderr, "connect failed: %s\n",
                modbus_strerror(saved_errno));
        goto cleanup;
    }

    if (modbus_set_slave(ctx, 1) == -1) {
        const int saved_errno = errno;
        fprintf(stderr, "set slave failed: %s\n",
                modbus_strerror(saved_errno));
        goto close;
    }

    rc = modbus_read_registers(ctx, 0, 2, regs);
    if (rc == -1) {
        const int saved_errno = errno;
        fprintf(stderr, "read failed: %s (errno=%d)\n",
                modbus_strerror(saved_errno), saved_errno);
        goto close;
    }

    if (rc != 2) {
        fprintf(stderr, "short read: expected=2 actual=%d\n", rc);
        goto close;
    }

    printf("reg[0]=%u (0x%04X)\n", regs[0], regs[0]);
    printf("reg[1]=%u (0x%04X)\n", regs[1], regs[1]);
    exit_code = 0;

close:
    modbus_close(ctx);
cleanup:
    modbus_free(ctx);
    return exit_code;
}
```

保存为 `rtu_master.c`，编译并运行：

```bash
gcc -std=c11 -Wall -Wextra rtu_master.c -o rtu_master \
    $(pkg-config --cflags --libs libmodbus)
./rtu_master
```

关键生命周期如下：

```text
modbus_new_rtu
    → 配置 response/byte timeout、debug（可在 connect 前）
    → modbus_connect
    → 配置 RS485 serial mode / RTS（若需要；必须在 connect 后）
    → modbus_set_slave
    → read/write
    → modbus_close
    → modbus_free
```

`modbus_connect()` 成功只表示串口打开成功，不表示任何从机在线。从机地址错误、设备断电和 A/B 断线通常要到实际读写时才表现为超时。

`modbus_rtu_set_serial_mode()` 和 `modbus_rtu_set_rts()` 需要对已打开的串口 fd 执行 `ioctl`，因此不能放在 `modbus_connect()` 之前；若转换器自动切换方向，则通常无须调用这两个 API。

### 3.4 常用读写 API

```c
uint8_t bits[16];
uint16_t regs[16];

modbus_read_bits(ctx, addr, count, bits);             /* 0x01 */
modbus_read_input_bits(ctx, addr, count, bits);       /* 0x02 */
modbus_read_registers(ctx, addr, count, regs);        /* 0x03 */
modbus_read_input_registers(ctx, addr, count, regs);  /* 0x04 */

modbus_write_bit(ctx, addr, TRUE);                    /* 0x05 */
modbus_write_register(ctx, addr, value);              /* 0x06 */
modbus_write_bits(ctx, addr, count, bits);             /* 0x0F */
modbus_write_registers(ctx, addr, count, regs);        /* 0x10 */
```

返回值必须逐次检查：

- 读函数成功时返回读取的元素数量；
- 写单个元素成功时通常返回 1；
- 写多个元素成功时返回写入数量；
- 失败返回 `-1`，并设置 `errno`。

不要只判断 `rc >= 0`，还应比较返回数量与预期数量是否一致。

### 3.5 多从机的最小轮询

同一总线只需要一个 context，通过 `modbus_set_slave()` 切换目标地址：

```c
const int slave_ids[] = {1, 2, 3, 4};

for (size_t i = 0; i < sizeof(slave_ids) / sizeof(slave_ids[0]); ++i) {
    uint16_t regs[2];

    if (modbus_set_slave(ctx, slave_ids[i]) == -1) {
        continue;
    }

    int rc = modbus_read_registers(ctx, 0, 2, regs);
    if (rc == 2) {
        printf("slave=%d value=%u,%u\n",
               slave_ids[i], regs[0], regs[1]);
    } else {
        const int saved_errno = errno;
        fprintf(stderr, "slave=%d failed: %s\n",
                slave_ids[i], modbus_strerror(saved_errno));
    }
}
```

这段代码适合验证协议，不适合作为最终架构：离线设备会反复占满 timeout，也没有优先级、deadline、设备状态和总线恢复机制。第5章会把它演进为单 Worker + 请求队列。

### 3.6 抓包和逐层定位

建议按以下顺序联调：

1. 只连接一台从机，先用厂商工具或 `modpoll` 一类工具确认参数；
2. 打开 `modbus_set_debug(ctx, TRUE)` 查看 Tx/Rx 字节；
3. 对照手册检查 Slave ID、功能码、协议地址和数量；
4. 使用示波器或逻辑分析仪观察 UART TX、RX、DE 和总线 A/B；
5. 单设备稳定后再扩展到 4、16、32 台。

看到请求 `01 03 00 00 00 02 C4 0B` 时，可以逐项判断：

- `01` 是否为目标从机；
- `03` 是否与手册的数据区匹配；
- `0000` 是否处理了 0/1 基地址差异；
- `0002` 是否跨越了非法地址；
- CRC 字节是否完整；
- 主站发送结束后 DE 是否及时释放；
- 从机是否在 timeout 内开始响应；
- 相邻两帧之间是否满足静默时间。

软件 debug 只能看到操作系统交给程序的字节。若怀疑方向切换、电气干扰、终端匹配或实际线上波形，必须使用硬件仪器。

**本章小结：** `modbus_connect()` 成功只代表串口已打开，读写成功才验证协议参数和设备可达；本章最小示例不含完整 deadline、重试、状态机和恢复逻辑，不能直接作为生产通信层。

---

## 第4章 Modbus RTU 的时序与异常

### 4.1 Response Timeout 与 Byte Timeout

libmodbus 提供两个容易混淆的超时：

**Response Timeout** 限制等待响应的时间。当 byte timeout 启用时，它主要约束首字节到达；当 byte timeout 为 0 时，它约束完整响应。

**Byte Timeout** 限制同一响应内相邻字节之间的最大间隔。它适合识别“收到半帧后停住”的情况，但设得过小会把正常的 USB/调度抖动误判为失败。

第一版建议关闭 byte timeout，以 50～500 ms 的 response timeout 起步，再按设备类型、功能码和实测 P95/P99 调整。项目初始基线可取普通请求 100 ms（见 6.7），但它不是验收值。

超时不是越长越稳。假设 32 台设备中一台离线，若 timeout 为 5 s，每轮就至少多阻塞 5 s；再叠加重试，整条总线会被一台设备拖慢。

### 4.2 deadline 与 timeout 的区别

- timeout：一次底层通信尝试最多等待多久；
- deadline：业务请求从提交到完成的最晚时刻，包括排队、重试、退避和 guard。

请求出队时必须计算剩余时间，并裁剪本次 timeout：

```text
remaining = deadline_monotonic - monotonic_now
quiet_reserve = max(inter_frame_gap, error_guard_reserve)
budget    = remaining - quiet_reserve

if budget < min_viable_attempt:
    以 EXPIRED 完成，不发帧

effective_timeout = min(request_timeout, budget)
```

`min_viable_attempt` 是请求发送和最短可能响应所需的最小时间余量；`quiet_reserve` 为本次实际发帧后的静默留出预算。正常路径至少取 `inter_frame_gap`，通信异常路径还要考虑 guard；两者在时间上可以重叠，因此取较大值而不是相加。每次重试前都要重新计算，不能把同一段静默重复计入。只在出队时检查一次，会让一个即将过期的请求继续占用总线数百毫秒。

deadline 必须基于单调时钟，例如 `clock_gettime(CLOCK_MONOTONIC, ...)`。墙钟可能因 NTP 校时或人工修改发生跳变，只适合日志时间戳。

### 4.3 迟到响应为什么危险

主站等待从机 A 超时，并不代表 A 不会在稍后响应。如果主站立即向从机 B 发请求，A 的迟到响应可能落入 B 的接收窗口：

```text
请求 A ──等待── timeout
                    ├── 立即请求 B ──────────┐
                    └──── A 的迟到响应 ──────┘ 发生交叠或错配
```

libmodbus 通常能通过地址、功能码和长度发现错配，但旧数据仍可能造成坏帧、CRC 错误或下一笔事务异常。因此通信错误后需要迟到响应隔离，而不是立刻访问下一个从机。

### 4.4 flush 的能力边界

`modbus_flush(ctx)` 可以丢弃调用时已经到达串口接收缓冲区的数据，但无法删除“未来才到达”的迟到响应。

可靠的异常后处理顺序为：

```text
立即保存 errno
    → 必要时 modbus_flush
    → 等待 guard interval
    → 下一次发送前再 drain/flush
    → 发送下一笔请求
```

其中 guard interval 要通过抓包校准。项目初始可取 10 ms；如果设备在超时后仍可能延迟数十毫秒响应，则应增大 guard 或修正 timeout。不要在每次正常请求前无条件 flush，因为这会掩盖时序问题，也可能丢弃仍有诊断价值的数据。

### 4.5 帧间隔与 guard interval

两者目的不同：

| 参数 | 触发时机 | 目的 |
| --- | --- | --- |
| `inter_frame_gap` | 每笔事务之后 | 满足 RTU 的 t3.5 帧边界要求 |
| `guard_interval` | 超时、坏帧等通信异常之后 | 隔离未来可能到达的旧响应 |

帧间隔是总线级义务：任何实际发送或接收的帧之后都不能省略，包括成功、失败和切换从机。入队后即过期、总线不可用或尚未发帧便取消的纯软件终态不产生帧，因此不需要额外等待。libmodbus 负责帧收发，但应用层 Worker 仍应显式保证事务之间的总线静默。

项目在 115200 bit/s 下可先设置 `inter_frame_gap_us = 1750`；低波特率应按实际字符位数计算 3.5 字符时间，并向上取整。

### 4.6 先保存 errno

任一 libmodbus API 返回 `-1` 后，应立即保存：

```c
int rc = modbus_read_registers(ctx, addr, count, regs);
if (rc == -1) {
    const int saved_errno = errno;

    /* 后续 flush、close、日志函数都可能改变 errno。 */
    modbus_flush(ctx);
    fprintf(stderr, "%s\n", modbus_strerror(saved_errno));
}
```

libmodbus 定义了扩展错误码，错误文本应使用 `modbus_strerror(saved_errno)`，而不只是标准 `strerror()`。

### 4.7 四类异常

工程代码不应在各调用点零散判断 errno。应集中通过一个 `mb_map_error()` 将错误映射为以下四类，再决定重试、设备状态和总线状态：

| 分类 | 含义 | 典型错误 | 重试 | 对设备失败计数的动作 |
| --- | --- | --- | --- | --- |
| `LOCAL_ERROR` | 报文未发出，本地参数或配置错误 | `EINVAL`、`EMBMDATA`、提交校验失败 | 否 | 不变 |
| `PROTOCOL_EXCEPTION` | 从机返回合法异常响应 | `EMBXILFUN`、`EMBXILADD`、`EMBXILVAL`、`EMBXSFAIL`、`EMBXACK`、`EMBXSBUSY`、`EMBXNACK`、`EMBXMEMPAR` | 通常否；BUSY 可退避重试 | 清零，设备可达 |
| `DEVICE_COMM_ERROR` | 已尝试通信，但未得到可用响应 | `ETIMEDOUT`、`EMBBADCRC`、`EMBBADDATA`、`EMBBADSLAVE` | 按语义有限重试 | 逻辑请求最终失败时 +1 |
| `BUS_ERROR` | 串口、链路、路径或权限不可用 | `EIO`、`ENODEV`、`ENXIO`、`ENOENT`、`EACCES`、`EBADF` | 不在原地重试 | 不变 |

几个关键判断：

- `EMBMDATA` 往往是数量超过协议上限等本地检查失败，不能把健康设备打成离线；
- 合法 Modbus Exception 表明设备在线，应更新 `last_reachable` 并清零通信失败计数，但不能更新业务数据；
- `EMBXACK` 表示设备已接受但需要更长处理时间，应延后读取状态而非立即重发；`EMBXSFAIL` 表示设备可达但内部故障，应单独增加 `device_fault_count` 并告警；
- `BUS_ERROR` 还须区分子类：曾经成功连接后出现的 `EIO`、`ENODEV`、`ENXIO`、`EBADF` 或拔出后的 `ENOENT` 属于可恢复链路故障；首次打开即 `EACCES` 或路径本就不存在导致的 `ENOENT` 多为不可自愈配置故障，应直接进入 `DOWN`、高级别告警并采用分钟级低频重试，避免刷屏；
- `EINTR`、`EAGAIN` 只有在能够确认请求尚未部分发送时，才可在 deadline 内免费重试。否则先 `modbus_flush()` 并保证至少 `t3.5` 静默；动作类写不得走无法确认发送阶段的免费重试路径。优先使用 `SA_RESTART` 或在线程中屏蔽无关信号，从源头减少 `EINTR`；
- 未识别的 errno 应保守归类并记录原始数值与 `unknown_errno_count`，不能静默忽略。

错误处理路径可归纳为：

```text
libmodbus 返回 -1 → 立即保存 errno
  ├─ 本地参数/提交校验错误       → LOCAL_ERROR：不发帧、不重试
  ├─ EMBX* 合法异常              → PROTOCOL_EXCEPTION：设备可达
  │    ├─ BUSY                   → 允许时退避重试
  │    ├─ ACK                    → 延后读状态
  │    └─ Slave Failure          → device_fault_count +1 并告警
  ├─ timeout/坏 CRC/坏响应        → DEVICE_COMM_ERROR：flush + guard，按语义有限重试
  ├─ 可恢复串口/链路故障          → BUS_ERROR：进入 RECONNECTING
  ├─ 首次连接的权限/路径配置故障   → BUS_ERROR：进入 DOWN 并低频重试
  └─ 未识别错误                  → 保守按通信错误处理，并保留原始 errno
```

### 4.8 写操作超时的不确定性

写请求超时只说明主站没有收到确认，不能证明从机没有执行。响应可能在链路上丢失，而写入已经生效。

因此需要区分：

- 幂等写：重复执行结果相同，如“将模式设为 3”；
- 动作类写：重复执行会产生额外副作用，如“计数加一”“切换状态”“触发一次动作”。

幂等写可在策略允许时有限重试；动作类写超时后通常不能自动重试，应返回“结果未知”，由上层读取状态或人工确认。协议设计阶段应优先采用 set-value，而不是 toggle/increment/trigger。

**本章小结：** timeout 约束一次尝试，deadline 约束整个业务请求；实际帧后保证 t3.5，通信异常后增加 guard；errno 必须先保存再集中分类，写 timeout 表示结果未知而不是未执行。

---

## 第5章 一主多从 Modbus RTU 软件架构

### 5.1 分层与职责

推荐结构如下。下行是命令和采集计划，上行是缓存数据、状态和事件；业务读取缓存时不应穿透并阻塞总线：

```text
            下行：命令/采集计划                 上行：数据/状态/事件
Application / UI / Cloud ──────────────────────────────────────┐
    ↓ 业务命令                                     ↑ 缓存读取  │
DeviceManager（映射、转换、缓存）                  ↑ 状态/告警  │
    ↓                                              │           │
Scheduler（周期、优先级、错峰）                    │           │
    ↓ submit()                                     │           │
modbus_bus + 有界请求队列                          │           │
    ↓                                              │           │
唯一 Bus Worker（串行、重试、静默、恢复）          │ 完成回调  │
    ↓                                              │           │
libmodbus → 串口 → RS485 → Slave 1 ... Slave 32 ──┴───────────┘
```

职责边界：

| 层 | 负责 | 不负责 |
| --- | --- | --- |
| libmodbus | RTU 组帧、CRC、串口收发、响应校验 | 队列、轮询、设备健康 |
| Bus Worker | 串行事务、异常分类、有限重试、总线静默、恢复 | 温度/电压等业务含义 |
| DeviceManager | 寄存器映射、数据转换、设备缓存 | 直接访问串口 |
| Scheduler | 周期、优先级、错峰和请求合并 | 执行底层事务 |

`modbus_t *` 和串口 fd 应封装在 `modbus_bus.c` 内部，不通过公共头文件暴露。这样调用方在结构上就无法绕过 Worker。

### 5.2 统一请求模型

每一笔读写都抽象为入队后由通信层独占的请求；提交成功后调用方不得再访问或修改请求节点及其缓冲区。示意结构如下：

```c
typedef enum {
    MB_OP_READ_BITS,
    MB_OP_READ_INPUT_BITS,
    MB_OP_READ_REGISTERS,
    MB_OP_READ_INPUT_REGISTERS,
    MB_OP_WRITE_BIT,
    MB_OP_WRITE_BITS,
    MB_OP_WRITE_REGISTER,
    MB_OP_WRITE_REGISTERS
} mb_operation_t;

typedef enum {
    MB_REQ_PERIODIC_POLL,
    MB_REQ_USER_CONTROL,
    MB_REQ_RECOVERY_PROBE
} mb_request_kind_t;

typedef struct {
    uint8_t max_attempts;
    uint32_t backoff_ms;
    bool retry_on_timeout;
    bool retry_on_busy;
} mb_retry_policy_t;

typedef struct mb_result mb_result_t;
typedef void (*mb_done_cb_t)(const mb_result_t *result, void *user_ctx);

typedef struct {
    uint64_t request_id;             /* submit 内部原子分配 */
    uint64_t correlation_id;         /* 调用方业务追踪 ID */
    uint8_t slave_id;
    mb_request_kind_t kind;
    mb_operation_t operation;
    uint16_t start_address;
    uint16_t quantity;
    union {
        uint16_t *regs;               /* 0x06 / 0x10 */
        uint8_t *bits;                /* 0x05 / 0x0F；每元素一字节 */
    } write;
    uint16_t write_count;
    uint32_t response_timeout_ms;
    uint32_t byte_timeout_ms;
    uint64_t deadline_monotonic_ms;
    mb_retry_policy_t retry_policy;
    mb_done_cb_t on_done;
    void *user_ctx;
} mb_request_t;
```

提交时同步校验：

- `slave_id` 在 1～247，默认禁用广播地址 0；
- 读位（`0x01`/`0x02`）数量不超过 2000，写多位（`0x0F`）不超过 1968；
- 读寄存器（`0x03`/`0x04`）数量不超过 125，写多寄存器（`0x10`）不超过 123；
- 单写操作数量固定为 1；
- 写缓冲区类型与 operation 匹配，`write_count == quantity`；
- 地址加数量不超过 `0x10000`；
- timeout、deadline 和回调参数有效。

写入数据应在 submit 时复制进通信层拥有的队列节点，调用方返回后即可释放原缓冲区。读取结果可由通信层在回调期间提供，但必须明确其生命周期；更简单稳妥的做法是让回调立即复制到 DeviceManager 缓存。

### 5.3 完成契约

> 每个成功入队的请求，其完成回调必须恰好调用一次。

这条不变式解决“请求已经提交，但调用方永远等不到结果”的问题。接口应明确区分两条路径：

```text
submit 返回 -1
    → 请求未入队
    → 通过 reject_code 同步说明 INVALID / QUEUE_FULL / STOPPED / COALESCED
    → 永远不调用完成回调

submit 返回 0
    → 请求已入队
    → 无论成功、失败、排队过期、总线不可用或停机取消
    → 完成回调恰好调用一次
```

Worker 内部采用单一出口最容易守住契约：所有处理分支最终汇聚到 `done:`，统一更新状态、记录日志、调用回调和释放节点。

本文选择如下合并契约：去重在 submit 内、队满检查之前执行，仅用于周期采集；若命中相同 `slave_id + operation + start_address + quantity + kind` 的未执行请求，则返回 `-1/MB_REJECT_COALESCED`。Scheduler 将其视为正常去重而不告警，该请求未入队，因此不产生回调。

完成回调在 Bus Worker 线程上下文中、完成总线静默之后同步执行。回调必须非阻塞，不得持有会与 submit 竞争的锁，也不得在回调内同步等待另一笔总线请求完成；允许 fire-and-forget 式 submit。推荐回调只复制结果到 DeviceManager 缓存并唤醒等待者，数据库、UI、同步落盘等重业务应转交独立线程。

请求生命周期如下：

```text
submit
  ├─ 校验失败 / 队满 / 已停机 / 命中合并 → 同步拒绝（未入队、无回调）
  └─ 通过 → QUEUED → 出队
                       ├─ deadline 余量不足 → EXPIRED ─────┐
                       ├─ 总线不可用         → BUS_UNAVAILABLE ─┤
                       └─ RUNNING → SUCCESS / RETRY_WAIT / FAILED ┤
                                      └──────→ RUNNING             │
                              停机取消 → CANCELLED ────────────────┘
                                                                  ↓
                                                        完成回调恰好一次
```

停机时应先关闭提交入口。正常宽限上限 `shutdown_grace` 可设为“单笔最大 timeout + guard + 帧间隔”；超出后强制 `modbus_close()` 解除阻塞，将当前及 pending 请求逐一以 `CANCELLED` 完成，最后释放 context 并 `pthread_join()`。不要直接丢弃队列，否则同步等待的业务线程可能永久挂起。

### 5.4 Worker 的执行流程

```text
取出请求
  → 总线状态检查（非 CONNECTED → 以 BUS_UNAVAILABLE 完成）
  → 重新计算 remaining 和 budget
       budget < min_viable_attempt → 以 EXPIRED 完成，不发帧
  → effective_timeout = min(request_timeout, budget)
  → 分别设置 response timeout、byte timeout，并分别检查返回值
  → modbus_set_slave → 调用对应 libmodbus API
  → 立即保存 errno → mb_map_error()
       ├─ OK / PROTOCOL_EXCEPTION → 清零通信失败计数
       ├─ DEVICE_COMM_ERROR → flush → 等 guard_interval → 再 drain
       │      attempt 未用尽且 deadline 允许 → 退避 → 回到 remaining 计算
       │      否则 → 本逻辑请求累计 1 次失败
       └─ BUS_ERROR → 进入总线恢复，不原地重试
  → 更新设备/总线状态 → 记录日志
  → 若本次实际发过帧，保证从帧结束起至少 inter_frame_gap 静默
  → 调用非阻塞完成回调 → 下一笔请求
```

设置两个 timeout 的返回值应分开检查，不能用短路表达式合并，否则第一个失败时第二个不会执行，context 可能停留在“半新半旧”的配置中。未发帧即过期、总线不可用或队列内取消的请求不需要额外等待 `inter_frame_gap`；该间隔约束的是总线上的实际帧，而不是纯软件状态迁移。

优先级只能改变尚未执行请求的顺序，不能中断正在进行的 RTU 事务。Modbus RTU 不支持抢占。

### 5.5 有界队列、优先级与过载

队列必须有固定容量。无限队列会把“总线处理不过来”变成不断增长的内存和越来越旧的数据。

项目初始容量可取 128，并做分级准入：

| 请求类型 | 初始配额 | 队满时 |
| --- | ---: | --- |
| 周期采集 | 最多 112 | submit 先去重；仍需入队但配额已满时拒绝 |
| 用户控制 | 预留 16 | 配额也用尽时拒绝 |
| 恢复探测 | 独立低优先级通道 | 空闲时执行，并设防饿死保底 |

仅仅把控制请求放进高优先级队列还不够；如果周期请求已经占满所有节点，控制请求仍无法入队，所以必须预留容量。

周期数据按 5.3 的合并键在队满检查前去重。历史采样应在业务层决定是否可丢，通信层不要猜测。

```text
队列容量 128
┌──────────────────────────────────────────┬──────────────┐
│ 周期采集区（≤112，submit 时可去重）       │ 控制预留 16  │
└──────────────────────────────────────────┴──────────────┘
恢复探测使用独立通道，不占用上述 128 个节点。
```

### 5.6 设备状态机

建议维护：

```text
ONLINE ──连续逻辑请求失败达阈值──► OFFLINE ──安排探测──► PROBING
   ▲                                   ▲                    │
   └────────── 探测成功/合法异常 ────────┴── 探测失败并退避 ──┘
```

规则示例：

- `DEVICE_COMM_ERROR` 才累计设备连续失败；
- 同一逻辑请求内部重试多次后仍失败，只累计 1 次；
- 成功响应或合法协议异常都证明设备可达，清零连续失败；
- 连续 3 个逻辑请求失败后标记 OFFLINE；
- OFFLINE 后停止常规轮询，由通信层以 5 s、10 s、30 s 等退避周期进行低频探测；
- 探测执行期间为 PROBING；成功恢复 ONLINE，再交回正常调度，失败则回到 OFFLINE 并继续退避。

恢复探测必须由通信层自行触发。如果通信层只被动消费队列，而 Scheduler 已停止向离线设备投递，那么设备永远没有恢复机会。探测默认在总线空闲时插入；若某台离线设备的探测已推迟超过当前退避周期的 2 倍，则在下一事务间隙强制插入一笔，每轮最多一笔，避免持续业务负载使恢复探测饿死。

### 5.7 总线状态机

设备状态和总线状态必须分开：

```text
CONNECTED ──链路错误/总线启发式命中──► RECONNECTING ──重连成功──► CONNECTED
                                             │  ▲
                             连续失败达阈值   │  │ 低频重试成功
                                             ▼  │
                                           DOWN ─┘
```

串口拔出常产生 `ENODEV`、`ENXIO`、`ENOENT`、`EIO` 等链路错误，可直接触发重连。但 A/B 总线断开时，串口设备仍存在，32 台从机会同时表现为 `ETIMEDOUT`。因此还需要总线级健康启发式，例如：

> 滑动窗口内失败率为 100%、失败数至少 8，且覆盖至少 `min(3, 当前应在线设备数)` 台不同从机，则认为更可能是总线故障。

总线故障期间暂停设备失败计数，避免把全部从机逐台误判离线。RECONNECTING 可采用 `200/400/800/1600/3200 ms` 指数退避，上限 5 s，并加入 ±20% 抖动。连续失败达到阈值后进入 DOWN：停止业务事务、以 `BUS_UNAVAILABLE` 快速完成 pending、上报持续告警，但仍以 30 s（可配置）周期低频重连，永不放弃恢复。DOWN 与 RECONNECTING 的区别是重试周期和告警级别，不是是否恢复。

**本章小结：** 通信层必须同时守住总线串行、队列有界、deadline 全程贯穿、成功入队后回调恰好一次，以及设备/总线状态相互独立这五条不变式。

---

## 第6章 稳定性与工程化设计

### 6.1 重试必须基于语义

建议把重试策略放入请求，而不是只有一个全局 `retry_count`：

| 请求类型 | 初始策略 | 原因 |
| --- | --- | --- |
| 读操作 | 最多 2 次尝试；timeout/BUSY 可重试 | 无写入副作用 |
| 幂等写 | 最多 2 次尝试；timeout/BUSY 可重试 | 重复执行结果相同 |
| 动作类写 | timeout 不自动重试；BUSY 可退避重试 | 执行结果可能未知 |
| 离线探测 | 1 次、短 timeout、不重试 | 避免离线设备占用总线 |

只对 `DEVICE_COMM_ERROR` 和明确允许的 `Slave Device Busy` 重试。本地参数错误、普通协议异常和链路故障都不应在原地盲目重试。禁止无限重试。

### 6.2 故障隔离

稳定系统要限制单个故障的影响范围：

- 单从机离线：有限重试后降频探测，不拖慢其他设备；
- 单请求非法：提交时拒绝，不改变设备健康；
- 单寄存器异常：记录功能码和异常码，不把整台设备判离线；
- 串口拔出：进入总线重连，不逐台累计失败；
- 大量积压：有界队列拒绝或合并，而不是耗尽内存；
- 慢命令：按请求配置 timeout，并受总 deadline 限制。

```text
故障源             影响应限制在                    不应扩散到
单请求非法      →  该请求（submit 即拒）        → 设备健康、总线
单寄存器异常    →  该寄存器/该次读写            → 整台设备离线
单从机无响应    →  该从机（降频探测）           → 其他从机的轮询
串口拔出        →  整条总线（统一重连）         → 逐台累计失败
请求积压        →  周期采集（拒绝/去重）        → 控制请求、内存
慢从机          →  该笔事务（timeout/deadline） → 后续请求的 deadline
```

### 6.3 总线恢复

总线恢复流程建议为：

```text
停止新事务
    → 保存故障原因和状态快照
    → modbus_close
    → 退避等待
    → modbus_connect
    → connect 成功后重新应用依赖 fd 的 RS485 serial mode / RTS 配置
    → 重新应用并检查 response/byte timeout 等运行参数
    → 执行少量探测
    → 恢复 CONNECTED
```

不建议无条件启用 `modbus_set_error_recovery(ctx, MODBUS_ERROR_RECOVERY_LINK | MODBUS_ERROR_RECOVERY_PROTOCOL)` 并完全依赖它。libmodbus 默认是 `MODBUS_ERROR_RECOVERY_NONE`，因此不调用该 API 就是本文推荐的初始状态。某些自动恢复路径可能长时间阻塞，应用层将难以控制 deadline、停机和日志；工程系统更适合显式管理恢复状态机。

USB 热插拔环境应使用稳定设备路径，并验证设备重新枚举后的权限、驱动状态和 DE/RE 控制。

### 6.4 RS485 硬件稳定性

软件无法补救所有物理层问题。现场至少检查：

- 使用双绞线，总线型菊花链连接，支线尽量短；
- 在线缆两端按阻抗需求配置终端电阻，避免每个节点都加终端；
- 在总线空闲时使用合理偏置，防止接收器输入悬空；
- 必要时连接信号参考地并考虑隔离、防雷和浪涌；
- 所有从机地址唯一，串口参数一致；
- 自动方向转换器与软件 RTS 控制不要重复配置；
- SoC UART + 外置收发器应检查 DE 释放时刻，避免截断末尾 CRC 或压住从机响应。

### 6.5 日志设计

每笔事务建议记录：

```text
wall_timestamp、monotonic_ms、deadline_remaining_ms、RequestID、CorrelationID、SlaveID、RequestKind、
Operation、Function、Address、Quantity、Result、saved_errno、
modbus_strerror、ExceptionCode、Attempt、QueueWaitMs、TxRxMs、
EndToEndMs、ErrorCategory、ConsecutiveFailCount、
DeviceStateBefore→After、BusState
```

Debug 模式可追加 Tx/Rx Hex，但生产环境默认关闭或限流，涉及凭据和业务数据时应脱敏。日志中必须保留原始 errno，不能只写“通信失败”。

将耗时拆成三段很重要：

- `QueueWaitMs` 高：调度或总线容量不足；
- `TxRxMs` 高：从机慢、timeout 过大或物理链路异常；
- `EndToEndMs` 高但前两者正常：可能是重试、guard 或回调处理过慢。

### 6.6 指标与告警

至少监控：

- 每台设备在线率、连续失败数、最后成功时间；
- 成功、timeout、CRC、异常响应和未知 errno 的计数；
- 事务耗时 P50/P95/P99；
- 队列深度、拒绝数和排队耗时；
- 各优先级请求的完成延迟；
- 总线利用率、重连次数、重连耗时和当前状态；
- guard、帧间隔和重试消耗的总线时间。

告警应区分“单设备离线”“多设备同时失败”“串口设备消失”和“队列持续过载”，否则现场只能看到一条没有行动指导意义的“Modbus error”。

### 6.7 容量预算与参数调优

不要脱离设备数量拍脑袋设轮询周期。可先估算：

```text
平均利用率 ρ ≈ Σ(每类事务频率 × 该类事务平均占用时间)
最坏窗口占用 ≈ Σ(窗口内事务数 × 该类事务 P95 占用时间)
              + 离线设备 timeout 开销
```

事务占用时间包含请求发送、从机处理、响应接收、`inter_frame_gap`，以及按发生概率折算的重试和 guard。平均利用率用于容量预算，长期目标可控制在 60%～70%；最坏窗口占用用于校核突发余量，必须低于 100%。

项目第一版可使用以下待校准基线：

| 参数 | 初始值 |
| --- | --- |
| 串口 | 115200、8N1；必须与从机一致，部分设备为 8E1 |
| 普通 response timeout | 100 ms |
| byte timeout | 0，第一版关闭 |
| `inter_frame_gap` | 1.75 ms（115200 下） |
| `guard_interval` | 10 ms |
| `min_viable_attempt` | 20 ms |
| 队列容量 | 128；周期 112、控制预留 16 |
| 离线阈值 | 连续 3 个逻辑请求通信失败 |
| 离线探测 | 5 s 起，10 s、30 s 退避封顶 |
| 总线重连 | 200 ms 指数退避至 5 s，±20% 抖动 |
| DOWN 低频重连 | 30 s；权限/路径配置故障可延长到分钟级 |
| 目标总线利用率 | 60%～70% |

调优方法：

1. 对每种设备、功能码和寄存器块执行不少于 100 次事务；
2. 记录正常响应 P95/P99 和最大值；
3. timeout 应覆盖合理尾延迟，但不能掩盖故障；
4. 逐步下调帧间隔并观察 CRC/timeout，确认严格从机的边界；
5. 注入设备断电、A/B 断线、半帧、USB 拔出和异常响应；
6. 由 1 台扩展到 4、16、32 台，重新验证利用率；
7. 完成 24 小时、72 小时和 7 天长稳测试。

所有调优结果应记录测试日期、设备型号、固件版本、波特率、接线长度和现场环境，确保可复现。

按上述基线估算：response timeout 为 100 ms、读操作最多尝试 2 次、异常 guard 为 10 ms、帧间隔为 1.75 ms。guard 已覆盖 `t3.5`，故单个逻辑读请求最坏约为 `2 × (100 + max(10, 1.75)) = 220 ms`；连续 3 个逻辑请求失败判离线约需 `660 ms`。若 32 台设备因 A/B 断线全部无响应，总线启发式应在 8 笔失败、约 0.88 s 内命中，早于逐台判离线。该算例未计退避、请求发送和调度开销，只用于检查参数数量级；若 timeout 改为 5 s，同类故障会把判离线时间放大到数十秒。

### 6.8 上线检查清单

```text
[ ] 设备确实支持 Modbus RTU，而不是 RS485 私有协议
[ ] 所有 Slave ID 唯一，未误用广播地址 0
[ ] 波特率、数据位、校验位、停止位一致
[ ] 已验证寄存器 0/1 基地址、数据类型、倍率和字序
[ ] 一条总线只有一个 Worker 和一个 modbus_t
[ ] timeout、deadline、有限重试和帧间隔均已实现
[ ] 写超时区分幂等操作与动作类操作
[ ] flush 后存在迟到响应 guard
[ ] 单设备状态与总线状态分离
[ ] 队列有界，控制请求有预留容量
[ ] 每个成功入队请求的回调恰好一次
[ ] 停机能取消并完成全部 pending 请求
[ ] 日志包含原始 errno、异常码、耗时和状态迁移
[ ] 已完成单设备、多设备、断线、热插拔和长稳测试
```

**本章小结：** 稳定性来自明确的故障边界、可计算的时间预算和完整的可观测性，而不是盲目加长 timeout 或增加重试次数。

---

## 附录 A 要点速查（FAQ）

### A.1 Modbus、Modbus RTU 和 RS485 有什么区别？

Modbus 定义数据模型和操作语义；Modbus RTU 定义串行链路上的二进制帧、CRC 与时序；RS485 定义差分电气接口。RS485 上可以运行 Modbus RTU，也可以运行其他协议。

### A.2 UART 和 RS485 是一回事吗？

不是。UART 产生串行字节流，RS485 收发器将其转换为适合多节点和较远距离传输的差分信号。常见系统是 UART 后接 RS485 收发器。

### A.3 为什么 RS485 可以挂多台设备，通信却必须串行？

两线 RS485 通常是共享的半双工介质，同一时刻只能有一个发送者。Modbus RTU 又采用严格的请求—响应模型，所以主站必须完成或终止当前事务后才能开始下一笔。

### A.4 为什么一条总线只用一个 `modbus_t` 和一个 Worker？

`modbus_t` 内保存当前 Slave ID、timeout 和串口状态。多个线程并发修改同一 context 会导致目标地址与响应错配；多个 context 并发写同一串口则会让字节交织。唯一 Worker 能从结构上保证串行访问。

### A.5 `modbus_connect()` 成功是否说明从机在线？

不是。RTU 模式下它主要表示串口成功打开和配置。只有实际请求收到成功响应或合法异常响应，才能证明某台从机可达。

### A.6 `40001` 为什么经常要在代码中写成 0？

`40001` 是数据区参考编号，报文携带的通常是从 0 开始的协议偏移量。不同厂商手册可能采用 0 基或 1 基写法，必须结合示例帧确认，不能一概而论。

### A.7 功能码 `0x03` 和 `0x04` 有何区别？

`0x03` 读取保持寄存器，通常可读写；`0x04` 读取输入寄存器，通常只读。两者都返回 16 位寄存器，但逻辑数据区不同。

### A.8 Modbus RTU 为什么需要 CRC？

CRC 用于发现链路传输中的位错误。它覆盖从机地址、功能码和数据，帧尾按低字节、高字节顺序发送。CRC 不提供纠错和安全认证。

### A.9 合法异常响应算设备离线吗？

不算。设备能返回结构正确、CRC 正确的异常帧，说明设备和链路可达。应清零通信失败计数，同时把功能码和异常码作为协议/业务错误报告。

### A.10 Response Timeout 和 Byte Timeout 有什么区别？

Response Timeout 主要限制等待响应开始或完整响应的时间；Byte Timeout 限制响应内部相邻字节间隔。byte timeout 为 0 时，通常由 response timeout 覆盖完整帧。

### A.11 timeout 和 deadline 有什么区别？

timeout 针对一次底层尝试；deadline 约束请求从提交到完成的整个生命周期，包括排队、重试和退避。每次尝试都应按 deadline 剩余时间裁剪 timeout。

### A.12 `modbus_flush()` 能解决迟到响应吗？

不能完全解决。它只能清除调用时已经到达的数据，无法清除未来才到达的响应。通信异常后还需要 guard interval，并可在下一次发送前再次 drain。

### A.13 t3.5 与 guard interval 是一回事吗？

不是。t3.5 是每帧之间的协议静默，用于识别 RTU 帧边界；guard interval 是超时或坏帧后用于隔离迟到旧响应的工程等待。异常后两者都可能需要。

### A.14 为什么不能所有错误都重试三次？

本地参数错误重试不会变好，链路错误应进入总线恢复，非法地址等异常响应需要修正请求，动作类写重试还可能造成重复执行。重试必须结合错误类别和操作幂等性。

### A.15 写请求超时后，从机是否一定没有执行？

不一定。可能是从机执行成功但响应丢失。因此动作类写不能自动重发；可通过读取最终状态、事务序号或设备侧去重机制确认结果。

### A.16 为什么离线设备会拖慢整条总线？

在线设备通常几十毫秒内响应，而离线设备会消耗完整 timeout；若再多次重试，单台离线设备的占用可能远高于所有在线设备之和。应有限重试、快速判定并低频探测。

### A.17 如何区分单设备故障和总线故障？

单个 Slave ID 持续失败而其他设备成功，更像设备故障；多个不同 Slave ID 在同一窗口同时 timeout 且没有成功事务，更像 A/B 断线或总线异常。串口设备消失类 errno 可直接判为链路故障。

### A.18 优先级队列能否中断正在执行的低优先级请求？

不能。RTU 事务不可抢占。优先级只决定下一笔执行什么，所以还需要合理的单笔 timeout，防止低优先级请求长时间占线。

### A.19 为什么请求队列必须有界？

总线吞吐有限。无限队列只会积累过期数据、增加内存并放大延迟。有界队列可以显式暴露过载，并通过预留、拒绝、合并和错峰保持系统可控。

### A.20 如何估算一条总线能轮询多少设备？

不能只看波特率。容量预算用平均占用时间计算平均利用率，并把长期目标控制在约 60%～70%；再用 P95 占用时间和离线 timeout 开销校核最坏窗口是否低于 100%。占用时间应包含发送、处理、响应、帧间隔以及重试/guard 的期望开销。

### A.21 为什么生产环境还需要抓包？

应用日志只能解释程序看到了什么；逻辑分析仪或示波器才能验证线上是否真的发送完整、DE 是否及时切换、从机何时响应以及是否存在波形反射和干扰。定位偶发 CRC 与 timeout 时，软件和硬件证据需要互相印证。

### A.22 一个可靠的 Modbus RTU 系统最重要的设计点是什么？

可以概括为六点：单 Worker 串行访问、有界队列、贯穿全流程的 deadline、按语义有限重试、设备/总线两级状态机、完整可观测性。协议 API 很简单，长期稳定性主要来自这些边界和约束。

---

## 附录 B 术语与缩写

| 术语 | 含义 |
| --- | --- |
| ADU / PDU | ADU 是线上完整应用数据单元；PDU 是其中的功能码和数据部分。RTU ADU 还含从机地址与 CRC。 |
| DE / RE | RS485 收发器的发送使能/接收使能控制。 |
| `t1.5` / `t3.5` | RTU 帧内最大字符间隔 / 相邻帧之间的最小静默时间。 |
| timeout / deadline | timeout 限制一次底层尝试；deadline 限制从提交到完成的整个逻辑请求。 |
| guard interval | 通信异常后隔离迟到旧响应的工程等待，不等同于 `t3.5`。 |
| attempt / 逻辑请求 | attempt 是一次底层尝试；一个逻辑请求可包含有限次 attempt，设备失败计数按最终逻辑结果累计。 |
| `min_viable_attempt` | 值得发起一次尝试所需的最小时间余量，不含已单独预留的帧间隔与 guard。 |
| 爆炸半径 | 单个故障可能影响的最大系统范围；故障隔离的目标是限制该范围。 |

---

## 延伸阅读

- [RS485 Modbus RTU 通信层引导文档](project%20design/guidance.md)
- [RS485 多设备 Modbus RTU 通信方案](project%20design/RS485%20多设备%20Modbus%20RTU%20通信方案_v0.2.md)
- [libmodbus 在 Linux 平台下的使用教程](project%20design/libmodbus%20在%20Linux%20平台下的使用教程.md)

本文用于建立统一认知和设计原则；具体结构体、接口契约、错误映射和现场测试项以项目设计文档的当前版本为准。
