# eRPC：从嵌入式远程调用理解 RPC 框架

> 目标：了解 RPC 解决什么问题，用伪代码看懂 eRPC 的调用过程，再了解它适合哪些嵌入式场景。
>
> 核心结论：**RPC（Remote Procedure Call，远程过程调用）让程序通过函数接口调用另一端的功能。eRPC（Embedded RPC）主要用于多芯片和异构多核嵌入式系统，用 IDL 描述接口，生成通信代码，底层可使用 UART、SPI、RPMsg 等通道。它简化了通信代码，但仍要考虑远端延迟、故障和内存差异。**

本文按「技术定位 → 基本术语 → 伪代码示例 → 核心机制 → 技术对比」展开，以 **EmbeddedRPC/eRPC 1.14.0** 为参考。示例说明主控如何调用采集 MCU 的功能，具体实践留到下一阶段。《官方仓库》（参考 1）、《1.14.0 发布页》（参考 2）

## 第一章、是什么，以及为什么存在

### 1.1、eRPC 解决什么问题

**eRPC 把跨芯片、跨核的通信包装成函数调用，自动生成打包、解包和分发请求的代码。**

假设 Linux 主控负责界面和业务，采集 MCU 负责 ADC（模数转换）采样和温度计算。主控要读取温度，却不能直接调用 MCU 内部的函数。

不使用 RPC 时，双方通常手写一套通信协议：

```text
主控：构造 READ_TEMPERATURE 命令、填写通道、发包、等响应、解包
MCU：收包、识别命令、提取通道、读温度、构造响应、发回

接口增加到几十个后：命令号、参数顺序、长度、错误处理都要维护两份
```

使用 eRPC 后，主控可以这样读取温度：

```text
temperature = sensor.getTemperature(channel)
```

两端仍要通信，但打包、解包和分发由生成代码及 eRPC 运行时处理。IDL（接口描述语言）规定双方的接口，真正读取温度的代码仍由开发者编写。

读取温度、修改配置等操作适合用函数接口表达。直接收发消息也能做到，但要自己维护消息含义、参数格式、请求与响应的对应关系，以及该调用哪个函数。eRPC 通过接口定义和生成代码减少这些重复工作。持续传输采样数据或向多个接收方广播事件时，数据流或发布订阅（发送方发布消息，订阅方接收）可能更合适。

### 1.2、「远程」可以只隔着一颗芯片或一个处理器核

```text
Linux 主控 / MCU A                              采集 MCU / MCU B
+----------------------------+                +----------------------------+
| 业务：getTemperature(0)     |                | 业务：读取 ADC、换算温度    |
|             |              |                |             ^              |
| 生成的客户端 Stub          |                | 生成的服务端 Shim          |
|             |              |                |             ^              |
| eRPC 运行时 + Codec        |                | eRPC 运行时 + Codec        |
|             |              |                |             ^              |
| Transport                  |<-- UART/SPI -->| Transport                  |
+----------------------------+                +----------------------------+
                  请求向右，响应向左

异构多核 SoC：同样的上下层结构，Transport 可以对接 RPMsg
```

跨核时，两端可能共享物理 RAM，但看到的地址、Cache（缓存）、操作系统和任务调度方式可能不同。共享 RAM 不代表能直接按本地函数的方式传参数。

上图简化了调用关系；分层和生成工具见《官方仓库》（参考 1）。

### 1.3、框架帮你做什么，工程还要决定什么

| 问题 | eRPC 提供什么 | 项目还要决定什么 |
| --- | --- | --- |
| 接口如何描述 | IDL、`erpcgen` | 参数含义、单位、有效范围 |
| 参数如何变成字节 | Codec、生成代码 | 可变长数据上限、版本兼容 |
| 字节如何到达对端 | Transport 与平台适配 | 端点、驱动、超时、连接恢复 |
| 远端如何执行正确函数 | 服务注册、方法分发 | 业务实现、在哪个任务中执行、访问权限 |
| 执行失败如何解释 | 运行时状态与错误处理入口 | 业务错误码、重试、幂等、降级 |

**RPC 与本地函数调用有什么不同？** 两端各自执行程序，没有共同的调用栈，也不能默认共用内存地址。普通指针不能直接交给对端访问，业务函数在远端的任务或主循环中执行。调用还要经过编码、通信和远端调度，因此会有额外延迟，也可能失败。没收到响应时，远端可能没执行，也可能已经执行，只是响应没到。

eRPC 的过程很直观：一端发出字节，另一端还原参数并调用函数。理解这个过程后，再看网络 RPC 框架，就更容易分清基本调用机制与额外的服务管理能力。

## 第二章、基本术语与调用关系

### 2.1、生成代码与处理请求发生在不同阶段

```text
构建时：描述接口、生成代码

                      sensor.erpc（IDL）
                              |
                           erpcgen
                              |
                +-------------+-------------+
                |                           |
         客户端 Stub / 类型定义       服务端 Shim / 类型定义
                |                           |
         编入主控程序                  编入 MCU 固件

运行时：传递请求、执行方法、返回结果

业务调用 -> Stub -> Codec -> Transport
                                  |
业务实现 <- Shim <- Codec <- Transport
```

**构建程序时，`erpcgen` 根据 IDL 生成源代码；程序运行后，eRPC 运行时负责处理请求。** MCU 接收调用时，不需要解析 IDL 或启动生成器。

### 2.2、术语和它们在代码中的位置

| 术语 | 先这样理解 | eRPC 中常见的名字 |
| --- | --- | --- |
| Client | 发起调用的一端 | C++ `ClientManager` |
| Server | 接收请求并调用业务函数的一端 | `SimpleServer` |
| Service / Interface | 一组相关的远程方法 | IDL `interface SensorService` |
| Method | 一个可被远端调用的方法 | `getTemperature` |
| IDL | 两端共同认可的接口说明 | `sensor.erpc` |
| Stub | 客户端代理，把函数调用变成请求 | 生成的 `sensor_client.cpp` |
| Shim / Skeleton | 服务端适配代码，把请求转成业务调用 | 生成的 `sensor_server.cpp` |
| Codec | 参数与字节之间的转换器 | `BasicCodec` |
| Transport | 字节的收发通道 | `TCPTransport`、UART、RPMsg 适配 |
| MessageBuffer | 存放一条消息的内存 | C++ `MessageBuffer` |
| MessageBufferFactory | 分配和回收消息缓冲区的组件 | 动态、静态或特定传输的工厂 |
| Service ID / Method ID | 请求中的接口与方法编号 | IDL `@id(...)` |
| Sequence | 把响应与本次请求关联起来的序号 | 请求与响应中的 `sequence` |
| Oneway | 发起调用后不等待 RPC 响应 | IDL `oneway heartbeat(...)` |

先了解这些组件各做什么，第三章再看它们如何配合。更多说明见《基础设施说明》（参考 3）；其中的旧 API 要按实际版本核对。

### 2.3、读到一个方法时，先问三个问题

1. **谁实现？** `getTemperature` 的实现属于采集端，主控端拿到的是代理。
2. **数据怎么过去？** 通道号被序列化，也就是转成字节发送；通常不会发送指针地址让 MCU 直接访问。
3. **什么时候返回？** 普通调用要等响应；`oneway` 不等响应，但发送本身仍可能阻塞，也就是需要等待才能继续。

Client / Server 表示调用角色。同一颗芯片可以调用对端，也可以向对端提供服务；共用通信通道时的注意事项见第四章。

## 第三章、最小 demo：目标、伪代码与结果

### 3.1、目标：主控调用采集 MCU 的三个接口

主控发起调用，采集 MCU 执行业务。用三个接口说明调用过程和等待响应的区别：

| 接口 | 业务目标 | 调用方式 |
| --- | --- | --- |
| `getTemperature(channel)` | 读取指定通道的温度，单位为毫摄氏度 | 等待响应并取得温度值 |
| `setLed(enabled)` | 设置 LED 状态 | 返回 `void`，仍等待响应 |
| `heartbeat(counter)` | 向采集端报告一次心跳 | `oneway`，不等待 RPC 响应 |

温度使用模拟值：通道 0 返回 `25375`，即 `25.375 ℃`；无效通道返回约定的错误标记。接口类型与 `oneway` 的规则见《IDL Reference》（参考 4）。

### 3.2、伪代码：从接口约定到远端执行

以下是 C/C++ 风格伪代码，只说明调用步骤；初始化和注册名称不对应具体 API。

本章假定通信与 RPC 处理成功，只展示调用过程和业务结果；通信或 RPC 失败的情况见 4.3。

```text
// 1. 两端约定同一组接口
interface SensorService {
    int32 getTemperature(uint32 channel);
    void  setLed(bool enabled);          // 没有业务返回值，仍有响应
    oneway heartbeat(uint32 counter);    // 不等待响应
}

// 2. 采集 MCU 提供业务实现
class SensorHandler {
    int32 getTemperature(uint32 channel) {
        if (channel >= 4) return INVALID_TEMPERATURE;
        return 25375 + channel * 1000;   // 模拟温度，单位为毫摄氏度
    }

    void setLed(bool enabled) {
        设置本地 LED 状态(enabled);
    }

    void heartbeat(uint32 counter) {
        记录收到的心跳(counter);
    }
}

// 3. 服务端初始化、注册服务，并在独立任务或主循环中处理请求
server = 创建服务端(Transport, Codec);
server.注册服务(SensorService, SensorHandler);
server.循环处理请求();                  // 接收 -> 解码 -> 调业务 -> 普通调用回复

// 4. 主控初始化客户端，取得接口代理
client = 创建客户端(Transport, Codec);
sensor = 创建 SensorService 代理(client);

// 5. 主控通过代理调用远端接口
temperature = sensor.getTemperature(0);
if (temperature == INVALID_TEMPERATURE) {
    报告无效通道();
} else {
    显示温度(temperature / 1000.0);      // 25.375 ℃
}

sensor.setLed(true);                     // 收到响应后继续
sensor.heartbeat(1);                     // 发送后继续，不等 RPC 响应
```

两端的接口与通信配置要匹配，Transport 可使用 UART、SPI 或 RPMsg。`sensor` 是客户端代理，读温度和设置 LED 的代码在采集 MCU 上执行。

读取温度时，调用按以下步骤进行：

```text
主控调用 getTemperature(0)
    -> 客户端编码：服务编号、方法编号、调用序号、channel=0
    -> Transport 将请求送到采集 MCU
    -> 服务端解码参数，分发到 SensorHandler
    -> 业务实现返回 25375
    -> 服务端编码响应，带回相同的调用序号与温度值
    -> 客户端校验、解码，返回 25375
```

### 3.3、结果：区分返回值、响应与执行完成

| 调用 | 预期结果 | 需要理解的边界 |
| --- | --- | --- |
| `getTemperature(0)` | 主控得到 `25375`，显示 `25.375 ℃` | 参数与返回值经过通信链路传递 |
| `setLed(true)` | 采集端设置 LED，主控收到响应后继续 | `void` 表示没有业务返回值，不表示没有响应 |
| `heartbeat(1)` | 主控发送后继续，采集端收到后记录心跳 | `oneway` 返回不能确认远端已经执行 |
| `getTemperature(4)` | 主控收到无效温度标记并报告错误 | RPC 收到正常响应，业务仍可能失败 |

这里的 `setLed` 设置完成后才回复。如果业务函数只是把动作放入队列，回复只能说明已接收任务，是否完成还要另行查询。

**调用过程：接口约定 → 客户端代理 → 编码与传输 → 服务端分发 → 业务执行 → 返回响应。** `oneway` 省去响应，远端仍要执行业务。

## 第四章、核心机制与注意事项

### 4.1、IDL 与生成代码：约定接口，生成通信代码

本地函数调用依靠编译器和 ABI（函数调用规则）传递参数、返回结果。RPC 两端各自运行程序，需要另外约定调用哪个方法、传哪些参数、怎样编码。

eRPC 根据 IDL 生成两端代码：Stub 把参数写入请求，Shim 从请求中读出参数，再调用业务函数。传输与缓冲区接口见参考 5，接入流程见《Getting Started》（参考 6）。

```text
接口定义：getTemperature(uint32 channel) -> int32

客户端适配：写 uint32 -> 发请求 -> 等响应 -> 读 int32
服务端适配：读 uint32 -> 调业务 -> 写 int32 -> 返回响应
```

**框架生成的是通信适配代码，温度怎么算、GPIO 怎么操作仍由业务实现决定。**

双方既要约定类型和编码，如 `uint32`、`int32`，也要约定通道范围、温度单位和无效值的含义。两端都能编译通过，不代表对数据的理解一致。

修改接口时，应固定已有服务和方法的编号，新方法使用新编号。旧编号不要改作其他用途。改变参数类型、顺序或结构布局，属于协议变更，需要考虑兼容和两端升级。

BasicCodec 按约定顺序编码字段，不能套用 Protobuf 通过字段编号识别数据、处理未知字段的兼容规则。接口编号等规则见《IDL Reference》（参考 4）。

### 4.2、Codec 与 Transport：编码数据，传输字节

```text
Codec：channel=0 -> 按协议编码的字节
Transport：把这些字节送到对端
Codec：收到的字节 -> channel=0
```

业务接口可以使用不同通信通道，但更换 Transport 时，仍要调整驱动、收发方式和缓冲区配置。

BasicCodec 的消息头包含编码版本、服务编号、方法编号、消息类型和调用序号，后面是参数或返回值。服务与方法编号各占 8 位，编号要在这个范围内。《BasicCodec 源码》（参考 7）

```text
采用 FramedTransport 的通道：

+----------------------+-----------------------+----------------------+
| 传输帧头             | BasicCodec 消息头     | 参数 / 返回值        |
| 长度、头校验、体校验 | 版本、服务、方法、类型| 按 IDL 约定顺序编码 |
|                      | 调用序号              |                      |
+----------------------+-----------------------+----------------------+
```

传输帧头记录消息长度和校验信息；RPC 消息头说明调用哪个方法、属于哪次调用。FramedTransport 的帧头为 6 字节，包含长度和 CRC16 校验信息。其他 Transport 的消息格式可能不同。《FramedTransport 源码》（参考 8）

理解传输时，要注意三点：

1. **一次读取不一定是一条消息。** UART 和 TCP 传输字节流，Transport 要根据消息边界收齐帧头和消息体。
2. **CRC 用来检查数据是否损坏。** 它不会自动重传，也不能验证发送方身份。校验失败后的恢复和重试要另外设计。
3. **普通指针只在本地有效。** 数组和字符串通常传内容与长度。共享内存传地址时，还要约定两端的地址映射、有效范围、缓存同步，以及谁能使用和释放数据。

`@shared` 可用于特定共享内存场景，传递地址而非序列化数据，前提与普通传参不同。RPMsg 零拷贝 Transport 需要匹配的消息缓冲区工厂；少复制一次，不代表整个调用都不复制数据。见《IDL Reference》（参考 4）、《MessageBufferFactory setup》（参考 9）。

### 4.3、请求与响应：匹配一次调用，不等于保证只执行一次

客户端创建并发送请求；普通调用还要等待并检查响应，`oneway` 不等待响应。服务端接收请求并分发给业务函数。普通调用通过响应类型和调用序号确认响应是否匹配。《ClientManager 源码》（参考 10）、《SimpleServer 源码》（参考 11）

需要区分三层结果：

| 层次 | 要回答的问题 | 示例与工程场景 |
| --- | --- | --- |
| 传输层 | 字节是否完整到达？ | 缓冲区不足、断线、校验失败 |
| RPC 层 | 请求与响应是否正确处理？ | 方法不存在、响应序号不匹配 |
| 业务层 | 这次操作是否达成目的？ | 通道越界、传感器故障 |

`INVALID_TEMPERATURE` 表示业务失败，通过正常 RPC 响应返回，含义不同于连接失败。复杂接口可分别返回业务状态和结果，避免把错误混入测量值。

最容易误解的是超时：

```text
客户端                  服务端
   | -- setLed(true) --> |
   |                     | 已经设置 LED
   |      X 响应丢失     |
   | -- 等待超时         |

客户端知道：没有按时取得结果
客户端不知道：远端究竟有没有执行
```

**超时表示结果未知，不能说明远端没执行。** 示例省略了超时处理。实际使用时，要结合 Transport 和调用代码设置等待上限；不能假定所有传输都能使用同一个 eRPC 超时 API。

能否重试，要看重复执行的后果。`setLed(true)` 重复执行通常还是亮灯，这叫幂等；`toggleLed()` 每执行一次都会翻转状态。扣减计数、启动电机任务等操作，可能需要业务请求标识 `requestId`、去重记录或状态查询接口。

调用序号用于匹配响应，**不能自动防止重试或重启后重复执行业务**。去重需要另行约定请求标识、有效期、保存范围和重启后的恢复方式。

第三章的区别同样适用：普通方法即使返回 `void`，也要等响应；`oneway` 不等响应，不能确认远端执行完成。业务函数如果只是把任务放入队列，回复也不代表任务完成。

耗时任务可先用 `startTask` 返回任务编号 `taskId`，再用 `getTaskStatus(taskId)` 查询是否完成。

### 4.4、任务与内存：函数在哪执行，数据由谁管理

简单服务端通常按「接收 → 分发 → 执行业务 → 回复」依次处理请求。一个方法执行太久，其他请求就要等。C++ `SimpleServer` 的 `run` 和 `poll` 都会处理消息；`poll` 还依赖 Transport 的 `hasMessage()`，不能认为它一定不会等待。《SimpleServer 源码》（参考 11）

温度采集可以由独立任务持续进行，RPC 方法只读取最新保存的值。耗时的校准或 Flash 写入可交给专门任务，并返回任务编号。这些任务要由应用安排，eRPC 不会自动创建线程池。

| 工程问题 | 需要明确的设计 |
| --- | --- |
| 在中断里调用同步 RPC | 交给任务处理，中断中不等待远端响应 |
| 多个线程共用 Client / Transport | 确认是否支持同时调用；简单做法是排队调用 |
| 两端同时发起请求 | 用匹配的仲裁方案，协调谁接收请求、谁接收响应 |
| 服务处理函数又同步调用对端 | 检查是否支持嵌套调用、任务能否继续运行，以及加锁顺序，避免互相等待 |
| 接收大数组或可变长字符串 | 限制长度，考虑缓冲区大小、分配失败和内存总量 |
| 把接收参数交给异步任务 | 明确谁管理和释放数据；必要时复制，避免适配代码返回后数据失效 |

双向调用可使用 `ArbitratedClientManager` 和 `TransportArbitrator`，协调同一通道上请求与响应的接收。不能让两个接收者随意对同一个普通 Transport 调用 `receive()`。《仲裁客户端》（参考 12）、《传输仲裁器》（参考 13）

消息缓冲区和解码后的业务数据使用的内存要分别考虑。即使消息缓冲区是静态的，生成代码、可变长参数或业务代码仍可能动态分配内存。移植时还要考虑对象和消息的分配、任务栈、锁及驱动，不能只看库文件大小。《移植说明》（参考 14）

后续阅读源码时，可按以下顺序跟踪一次调用：

| 阅读顺序 | 位置 | 想确认的问题 |
| --- | --- | --- |
| 1 | IDL 与生成的 Client | 服务编号、方法编号、参数写入顺序 |
| 2 | `ClientManager` | 请求如何发送，在哪里等待并校验响应 |
| 3 | `BasicCodec` 与 Transport | 字节如何编码，消息如何分帧与收齐 |
| 4 | `SimpleServer` 与生成的 Service | 怎样找到方法，业务在哪个任务或主循环中执行 |
| 5 | MessageBufferFactory 与业务实现 | 数据由谁拥有，何时释放，失败如何恢复 |

后续实践中，调用不通可依次检查：两端接口与运行时版本、请求和响应的传输方向、服务端是否运行、服务注册、方法编号和业务实现。接入硬件后还要检查驱动、端点和通信链路。收到响应但结果不对时，先核对类型、单位和业务状态。

## 第五章、技术对比与适用场景

### 5.1、这些技术分别做什么

| 技术 | 主要功能 | 与 eRPC 的关系 | 解决什么问题 |
| --- | --- | --- | --- |
| 手写 UART/SPI 命令协议 | 命令号、数据帧、响应包 | 可以手工实现与 RPC 类似的请求响应 | 接口很少时，是否值得引入生成器与运行时？ |
| RPMsg / RPMsg-Lite | 核间消息与收发端点 | 可作为 eRPC 的底层传输 | 不同处理器核之间怎样交换消息？ |
| Protobuf | 结构化消息定义与序列化 | 与 Codec 职责相近；单独使用还要补调用机制 | 数据如何跨语言编码，字段怎样演进？ |
| gRPC | 服务接口与调用过程 | 同属 RPC 框架，主要面向网络服务 | 网络服务如何调用、传输数据流和处理错误？ |
| eCAL | 发布订阅、服务调用与配套工具 | 也有请求响应，但整体更侧重数据交换 | 主机与局域网的数据流怎样组织、观察和回放？ |

RPMsg-Lite 的定位见《官方仓库》（参考 15），Protobuf 的职责见《官方概览》（参考 16），gRPC 的生成接口与调用模型见《官方介绍》（参考 17）；eCAL 的请求响应模式见《服务说明》（参考 18）。

RPMsg-Lite 负责传递消息，上层仍要规定消息是「读温度」还是「启动任务」。在它上面使用 eRPC，就能用接口和参数描述操作，并把请求分发到对应方法。

Protobuf 负责把数据结构转成字节，本身不完成服务选择、发起调用、等待和匹配响应。RPC 框架可以使用序列化工具，但还要处理完整的调用过程。

### 5.2、用项目问题做选择

**MCU 之间、Linux 与 MCU 之间或异构多核之间，需要调用一组明确的业务方法时，可以考虑 eRPC。** 要先确认平台支持 Transport 和运行时，再评估 RAM、Flash、任务调度和故障恢复的成本。

使用 eRPC 有三个前提：双方对方法、参数类型、单位和结果含义的理解一致；底层有可用的通信通道，并接入匹配的 Transport；两端能运行 eRPC，服务端能处理请求并执行业务。IDL 和生成代码简化通信代码，业务约定、通信通道和平台支持仍要由系统提供。

下表用于判断适用场景，不代表性能排名：

| 项目情况 | 优先考虑的方向 | 原因 |
| --- | --- | --- |
| 两颗 MCU 之间几十个配置、查询和控制接口 | eRPC | IDL 与生成代码减少重复协议适配 |
| 只有几个固定命令，代码空间极紧 | 精简命令协议 | 先比较维护成本与引入运行时的成本 |
| 已有 RPMsg 核间通道，需要调用远端能力 | 在 RPMsg 上使用 eRPC | RPMsg 传消息，eRPC 处理函数调用 |
| 网络服务需要成熟的多语言 RPC 生态 | gRPC | 围绕服务接口与网络调用能力组织开发 |
| 多进程持续交换图像、点云，需要录制回放 | eCAL 等数据通信中间件 | 核心需求是数据流与配套工具 |
| 硬实时闭环必须保证最大响应时间 | 先设计本地控制和等待时间有上限的通信 | 等待远端响应会让控制周期受远端调度和通信故障影响 |

这些技术可以组合使用：Linux 主控内部用数据通信中间件连接算法进程，主控用 eRPC 查询 MCU 的参数和状态，MCU 用本地任务处理实时采集与控制。按业务需求分工即可。

回顾温度调用：**IDL 约定接口，Stub 编码请求，Transport 传到对端，Shim 调用业务函数，再用响应送回结果。通信故障和结果未知的情况仍需另外处理。**

### 5.3、外部链接参考

以下按首次引用顺序列出。本文参考 1.14.0；`main` 源码链接用于延伸阅读，内容可能随上游更新。

1、eRPC 官方仓库：[EmbeddedRPC/erpc](https://github.com/EmbeddedRPC/erpc)

2、本文参考版本：[eRPC 1.14.0](https://github.com/EmbeddedRPC/erpc/releases/tag/1.14.0)

3、eRPC 基础设施与分层：[eRPC infrastructure](https://github.com/EmbeddedRPC/erpc/wiki/eRPC-infrastructure)

4、IDL、注解、参数与方法语法：[IDL Reference](https://github.com/EmbeddedRPC/erpc/wiki/IDL-Reference)

5、传输与消息缓冲区接口：[Transport（1.14.0）](https://github.com/EmbeddedRPC/erpc/blob/1.14.0/erpc_c/infra/erpc_transport.hpp)、[MessageBuffer（1.14.0）](https://github.com/EmbeddedRPC/erpc/blob/1.14.0/erpc_c/infra/erpc_message_buffer.hpp)

6、接入生成代码与裸机运行时：[Getting Started](https://github.com/EmbeddedRPC/erpc/wiki/Getting-Started)

7、基本消息编码：[BasicCodec](https://github.com/EmbeddedRPC/erpc/blob/main/erpc_c/infra/erpc_basic_codec.cpp)

8、消息长度与帧校验：[FramedTransport](https://github.com/EmbeddedRPC/erpc/blob/main/erpc_c/infra/erpc_framed_transport.cpp)

9、消息缓冲区工厂：[erpc_mbf_setup.h](https://github.com/EmbeddedRPC/erpc/blob/main/erpc_c/setup/erpc_mbf_setup.h)

10、客户端请求与响应检查：[ClientManager](https://github.com/EmbeddedRPC/erpc/blob/main/erpc_c/infra/erpc_client_manager.cpp)

11、服务端运行与消息处理：[SimpleServer](https://github.com/EmbeddedRPC/erpc/blob/main/erpc_c/infra/erpc_simple_server.cpp)

12、仲裁客户端：[ArbitratedClientManager](https://github.com/EmbeddedRPC/erpc/blob/main/erpc_c/infra/erpc_arbitrated_client_manager.cpp)

13、共享通道上的接收仲裁：[TransportArbitrator](https://github.com/EmbeddedRPC/erpc/blob/main/erpc_c/infra/erpc_transport_arbitrator.cpp)

14、平台、内存与操作系统移植：[Porting Guide](https://github.com/EmbeddedRPC/erpc/wiki/Porting-Guide)

15、核间消息传递：[RPMsg-Lite 官方仓库](https://github.com/nxp-mcuxpresso/rpmsg-lite)

16、结构化数据序列化：[Protocol Buffers Overview](https://protobuf.dev/overview/)

17、网络 RPC 接口与生成代码：[Introduction to gRPC](https://grpc.io/docs/what-is-grpc/introduction/)

18、eCAL 请求响应模式：[eCAL Services](https://eclipse-ecal.github.io/ecal/stable/getting_started/services.html)
