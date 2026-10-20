# eCAL：分布式通信中间件扫盲、代码阅读与面试准备

> 目标：理解 eCAL 的通信模型和它与 MQTT/DDS/Zenoh 的边界；能在机器人、车载或算法项目中快速定位初始化、发布、订阅、服务与传输配置代码；能清楚回答常见面试问题。
>
> 核心结论：**eCAL（enhanced Communication Abstraction Layer）是无中心 Broker 的通信中间件，提供「发布/订阅」和「服务/客户端」两种通信模式。同主机进程间可使用共享内存，跨主机可使用 UDP 多播或 TCP；发现注册与业务数据传输是两条不同的链路。它的工程特色是高吞吐数据交换，以及配套的监控、录制、回放和进程管理工具。**

本文配置与 C++ 示例以 **eCAL 6.x** 为主。5.x 项目常见 `ecal.ini`、旧头文件和 `AddReceiveCallback`；6.x 使用 `ecal.yaml` 并调整了 API，不能混抄。版本差异参见官方 《eCAL 6 迁移指南》（参考 1）。

## 第一章、eCAL 是什么，以及为什么选它

### 1.1、先用一张图理解

```text
主机 A                                              主机 B
+-----------------------------------+               +--------------------+
| 传感器进程 Publisher               |               | 算法进程 Subscriber |
|         |                         |               |         ^          |
|         +---- SHM ----> 本机算法   |               |         |          |
|         |                         |               |         |          |
|         +========= UDP / TCP ===============================+          |
|                                   |               |                    |
| 参数服务 Server <================ TCP ============= Client              |
+-----------------------------------+               +--------------------+
          ^                                                   ^
          +-------- 发现 / 注册：交换 Topic、服务、端点信息 -----+

Monitor：观察节点与 Topic       Recorder：订阅并落盘
Player：从文件重新发布          Sys：管理应用进程
```

图中的 UDP/TCP 是 pub/sub 数据链路；服务请求与响应通过 TCP 传输。发现注册负责让节点知道「谁在发布、谁在订阅、谁提供服务」，不负责替所有节点转发业务消息。通信库运行在应用进程里，Monitor 也不是中心 Broker。《官方项目介绍》（参考 2）、《服务通信说明》（参考 3）

与 MQTT 最大的差别有两点：

1. **消息不必经过中心 Broker。** 同机进程可以直接利用共享内存交换大块数据；网络上的发布者和订阅者通过可用传输层通信。
2. **工具围绕数据流水线组织。** 除了实时通信，还可以观察消息、采集实验数据，再把同一段输入交给算法反复处理。

### 1.2、为什么车载/机器人项目会选 eCAL

下面是工程选型时可采用的判断框架，不是对任意硬件的性能保证：

| 需求 | eCAL 的对应能力 | 典型例子 |
| --- | --- | --- |
| 同机大数据交换 | 共享内存传输 | 相机图像、点云、算法中间结果 |
| 多进程解耦 | 无 Broker 的 pub/sub | 采集、感知、融合、可视化独立运行 |
| 请求与响应 | Service / Client | 获取参数、读取诊断快照 |
| 算法问题复现 | Recorder + Player | 采集现场输入，离线重跑感知算法 |
| 跨语言集成 | 二进制传输与序列化包装 | C++ 发布，Python 分析 |
| 运行可观测 | Monitor + Sys | 查看 Topic 活动、管理应用启动 |

eCAL 的定位更接近**主机与局域网内的数据交换基础设施**。公网设备接入、跨 NAT、账号管理、持久消息队列和硬实时控制，都需要额外的架构设计。不能因为共享内存吞吐高，就推导出它适合 MCU 裸机或能保证控制周期的最坏时延。

## 第二章、核心概念与 Topic 设计

### 2.1、关键名词

| 名词 | 含义 | 看代码时常见名字 |
| --- | --- | --- |
| 初始化上下文 | 在进程中启动 eCAL 通信能力 | `eCAL::Initialize`、`eCAL::Finalize` |
| Topic | pub/sub 数据通道的名称 | `robot/1/lidar/scan` |
| Publisher | 向某个 Topic 发布样本 | `eCAL::CPublisher`、`Send` |
| Subscriber | 接收某个 Topic 的样本 | `eCAL::CSubscriber`、`SetReceiveCallback` |
| Data Type Information | 编码、类型名称、描述等元数据 | `SDataTypeInformation` |
| Registration | 传播节点、Topic、服务与传输端点信息 | `registration` |
| Transport Layer | 实际搬运数据的机制 | `shm`、`udp`、`tcp` |
| Service / Method | 请求响应接口及其方法 | `CServiceServer`、`CServiceClient` |
| Measurement | 录制得到的数据集合 | Recorder、HDF5 |

**Topic 名称、数据类型和发布进程身份是不同的东西。** 一个 Topic 可以有多个发布者；业务若只允许一个权威数据源，应在部署和协议中明确约束，不能仅靠 Topic 名字判断来源。

### 2.2、先分清「流、状态、事件、命令、服务」

一个实用的项目命名约定如下（不是 eCAL 的强制标准）：

```text
robot/1/camera/front/image      图像流
robot/1/lidar/scan              点云流
robot/1/state/pose              位姿
robot/1/state/battery           电量
robot/1/event/fault             故障事件
robot/1/cmd/velocity            控制指令
robot/1/cmd/ack                 业务执行结果

服务名：robot_1_config
方法名：GetConfig / SetConfig
```

| 类型 | 语义 | 建议业务策略 | 例子 |
| --- | --- | --- | --- |
| 高频流 stream | 更关心最新一帧 | 有界队列、过期丢弃、记录序号 | 图像、点云 |
| 状态 state | 需要知道当前值 | 周期发布，必要时提供快照服务 | 模式、电量 |
| 事件 event | 一次性事实 | 独立记录，明确遗漏与重试策略 | 故障、按钮动作 |
| 命令 cmd | 可能有副作用 | `requestId`、有效期、幂等、业务 ack | 任务下发 |
| 服务 service | 一次请求对应响应 | 明确目标实例、超时和错误码 | 参数读取 |

**发布过一次状态，不等于晚加入者能拿到它。** 普通 pub/sub 不应被当成 Retain 或历史查询接口；新节点需要当前值时，设计周期状态发布或 `GetState` 服务。

### 2.3、Topic 不是 Zenoh 的键表达式

业务可以用 `/` 做层级命名，但基本订阅应按明确的 Topic 名称设计。不要把 MQTT 的 `+/#` 或 Zenoh 的 `*/**` 直接写进 eCAL 普通 Subscriber，期待它自动匹配所有子 Topic。

需要动态订阅一组 Topic 时，应先发现实际名称，再按应用规则创建订阅；工具中的筛选规则也不等于通信 API 的匹配规则。Topic 名字相同仍不足以证明协议兼容，还要确认编码、字段、单位与版本。

## 第三章、组网与收发链路

### 3.1、从初始化到收发

```text
应用进程                            eCAL 通信库 / 其他节点
   | ---- 读取配置 -----------------> |
   | ---- Initialize ---------------> | 启动通信上下文
   | ---- 创建 Publisher/Subscriber ->| 注册 Topic、传播端点信息
   |                                  | 匹配订阅关系、选择可用传输层
   | ---- Send ---------------------> | SHM / UDP / TCP 搬运数据
   | <--- 接收回调 -------------------| 校验、投递到业务队列
   | ---- 创建 Server/Client -------->| 注册与发现服务
   | ---- 发起方法调用 -------------->| TCP 请求与响应
   | ---- 销毁通信对象 -------------->| 撤销资源
   | ---- Finalize -----------------> | 关闭通信上下文
```

初始化和注册传播需要时间。**`Initialize` 成功不等于对端已发现本节点，也不等于第一次 `Send` 有订阅者接收。** 对一次性关键数据，设计就绪握手或业务确认；演示程序里的固定 `sleep` 只能方便观察，不能作为生产就绪条件。

### 3.2、local 与 network 模式

6.x 默认配置中的 `communication_mode` 为 `local`；跨主机通信需要检查双方实际加载的配置。旧资料中的 cloud mode 指网络通信模式，不意味着数据会自动进入云平台。《网络配置教程》（参考 4）

| 模式 | 含义 | 适用场景 |
| --- | --- | --- |
| `local` | 通信范围限制在本机 | 单机算法流水线、离线开发 |
| `network` | 允许跨主机通信；同机仍可使用 SHM | 多计算单元、局域网测试系统 |

最小的 6.x 配置片段：

```yaml
# 合并到项目实际使用的 ecal.yaml；其他字段按该版本模板保留
communication_mode: network
```

### 3.3、发现注册与数据传输要分开排查

| 链路 | 需要确认的问题 | 常见误判 |
| --- | --- | --- |
| 注册 / 发现 | 注册传输、网络模式、多播可达性、超时 | 能看到 Topic 就认为载荷一定可达 |
| SHM 数据面 | 共享内存可见性、权限、传输域、容器隔离 | 同一物理机上的容器必然共享 SHM |
| UDP 数据面 | 多播组、端口、网卡、交换机、缓冲区 | 注册多播能通，所有数据多播就能通 |
| TCP 数据面 | 两端启用情况、优先级、端点可达性 | 发布端启用 TCP 就一定使用 TCP |
| 服务调用 | 主机名解析、TCP 连接、目标服务实例 | Topic 能收，服务就必然能调用 |

容器部署时，应同时核对网络命名空间、IPC/共享内存可见性和主机身份约定。仅调整网络设置无法自动解决 SHM 隔离；应按官方 《Docker 教程》（参考 5） 与所用版本配置复核。

## 第四章、传输选择、丢帧与共享内存

### 4.1、SHM、UDP、TCP 怎么选

| 传输 | 主要场景 | 优点 | 需要付出的代价 |
| --- | --- | --- | --- |
| SHM | 同主机进程间 | 避免通过网络栈搬运大块载荷 | 共享内存资源、同步、生命周期管理 |
| UDP 多播 | 网络上一对多 | 适合向多个订阅者分发 | 分片丢失、突发流量、网络多播配置 |
| TCP | 网络上的大块数据 | 有传输层重传和拥塞控制 | 每个订阅者的连接与发送开销 |

自动选择的含义是：**在双方启用的传输层中，按发布侧配置的优先级选择**，不是根据消息大小做任意智能切换。可用层与默认设置参见 《传输层说明》（参考 6）。

6.x 中，网络 pub/sub 使用 TCP 要同时检查发布侧优先级和订阅侧开关。例如下面的片段让跨主机通信优先 TCP；此处优先级是**传输层顺序**，不是控制消息调度优先级。《TCP 配置说明》（参考 7）

```yaml
publisher:
  layer:
    shm:
      enable: true
    udp:
      enable: true
    tcp:
      enable: true
  priority_network: [tcp, udp]

subscriber:
  layer:
    shm:
      enable: true
    udp:
      enable: true
    tcp:
      enable: true
```

这不是完整配置文件。对不同 Topic 采用不同策略时，可使用 Publisher/Subscriber 配置对象；避免一次修改全局配置，让所有高频小消息都走同一种传输。《运行时配置示例》（参考 8）

### 4.2、TCP 可靠不等于业务不丢消息

官方把 eCAL 的整体消息交付定位为 best effort。UDP 可能丢分片，TCP 链路之外仍可能丢整条消息，SHM 中慢消费者也可能错过被更新的样本。《消息丢失说明》（参考 9）

要区分四层含义：

1. **传输可靠性**：数据是否在链路上完整到达。
2. **中间件交付**：接收回调是否实际得到这条样本。
3. **应用排队**：业务队列是否接纳它，是否因积压被丢弃。
4. **业务执行**：动作是否执行、结果是否持久保存。

因此 `Send` 返回、TCP 接收成功和控制动作完成，不能画等号。对关键命令，发送侧记录待确认请求，接收侧按 `requestId` 去重，执行完成后返回明确结果；超时表示结果未知，不能直接判定「一定没执行」。

### 4.3、共享内存不自动等于零拷贝

普通 SHM 与零拷贝是不同路径：

```text
普通 SHM：应用载荷 -> 共享内存 -> 订阅进程自己的缓冲区 -> 回调
零拷贝原始接收：共享内存 ---------------------------> 二进制接收回调直接访问
```

零拷贝模式默认关闭。完整路径还取决于 API 与连接形态：Protobuf 仍需序列化，混合网络/SHM 发送或多缓冲可能改变发布侧拷贝行为。不能只看到 `zero_copy_mode: true` 就宣称整个算法链路零拷贝。《零拷贝机制说明》（参考 10）

图中的直接访问指原始二进制接收回调；字符串、Protobuf 等类型包装的业务回调仍可能涉及复制、对象构造或反序列化，不等于直接持有 SHM 载荷。

评估时应逐段数拷贝：设备采集、格式转换、序列化、eCAL 传输、队列交接、GPU 上传。即使中间件省去一次复制，其他环节仍可能占主要开销。

### 4.4、SHM 握手与多缓冲

SHM 可配置 `acknowledge_timeout_ms`，让发布侧等待订阅侧的读取确认或超时；多缓冲用于改善连续读写的冲突。这些机制涉及吞吐与阻塞的取舍，握手不是业务执行 ack，也不是持久消息队列。《SHM 层说明》（参考 11）

调参前先确定：允许漏几帧、最多能阻塞多久、每帧大小、订阅者数量，以及最慢订阅者的处理时间。控制线程不要在不了解阻塞上界时直接调用可能等待的发送路径。

## 第五章、服务、监控、录制与回放

### 5.1、服务是请求响应，不是 Topic 历史查询

pub/sub 回答「后续有哪些新数据」，服务回答「现在请执行一次方法并返回结果」。服务使用 TCP，跨主机时还要保证服务端主机名能被客户端正确解析。《服务教程》（参考 3）

| 场景 | 建议方式 | 需要补充的约定 |
| --- | --- | --- |
| 连续点云、图像 | pub/sub | 帧序号、采样时间、丢帧策略 |
| 获取当前参数 | `GetConfig` 服务 | 参数版本、单位、错误码 |
| 修改配置 | `SetConfig` 服务 | 幂等、校验、应用时机 |
| 长时间任务 | 服务受理 + Topic 报告进度 | `taskId`、取消和终态 |

服务名相同可能对应多个实例。读取项目时，确认客户端的实例选择和调用范围，不能默认只有一个服务器。调用接口和回调签名也应按实际版本核对。

### 5.2、Monitor：观察系统，不承担消息路由

Monitor 用于查看进程、Topic、服务及相关统计，支持检查消息内容等调试操作；运行它不等于启动通信中心。《Monitor 教程》（参考 12）

建议按「注册可见 -> 样本有活动 -> 类型可解释 -> 业务结果正确」逐层验证。Topic 的存在只提供第一层证据；频率正常也不能证明消息单位、时间戳或数据来源正确。

### 5.3、Recorder 与 Player：从实时数据到可重复输入

Recorder 订阅选定的数据并保存为 Measurement，录制数据使用 HDF5；分布式录制还涉及各主机上的录制客户端。《录制入门》（参考 13）、《录制架构》（参考 14）

Player 将录制数据重新发布，供订阅应用接收；可按回放需要控制播放过程。《Player 教程》（参考 15）

```text
实车 / 实验台输入 -> eCAL Topic -> Recorder -> Measurement
                                               |
                                               v
                                      Player -> 算法 -> 输出比较
```

工程上应额外保存：算法版本、参数、标定、消息定义、时钟约定与录制范围。**相同输入不自动保证相同输出**：随机数、线程调度、外部服务和实时时钟都可能影响结果。

回放环境应与现场控制环境隔离，特别是命令 Topic。还要防止实时发布者和 Player 同时向同名 Topic 发数据，使算法混入两套输入。

### 5.4、Sys：管理进程，不替代业务恢复逻辑

Sys 用于配置与管理一组应用进程，包括分布式场景中的启动、停止及状态观察。《Sys 教程》（参考 16）

业务仍需区分：进程已启动、通信实体已注册、必要数据已收到、算法已就绪。重启进程也不自动恢复应用队列和任务状态；应用应设计自身的恢复与重新同步流程。

## 第六章、业务实现要点

### 6.1、收到数据后的推荐路径

```text
Subscriber 回调（尽快返回）
        |
        v
校验来源、类型、长度、序号与时间戳
        |
        v
取得载荷所有权 / 反序列化
        |
        v
有界业务队列（明确满队列策略）
        |
        v
业务线程计算 -> 更新真实状态 -> 发布结果 / 返回业务 ack
```

回调通常由库的内部线程调用。传入数据的有效期不能随意延伸到回调之外；尤其是 SHM 零拷贝接收，不能把裸指针塞进异步队列后立即返回。需要异步处理时，应复制到自有缓冲区，或使用该 API 明确支持的所有权机制。《线程模型说明》（参考 17）

建议把队列长度、丢弃计数和最老样本年龄纳入监控。高频流可以只保留最新样本；事件和命令则应明确拒绝、告警或持久化策略，不能套用同一条「队满就丢」规则。

### 6.2、载荷与序列化

eCAL 核心传输二进制数据，结构化类型可使用 Protobuf、Cap’n Proto、FlatBuffers 等包装；Protobuf 不是核心通信的强制载荷格式。《pub/sub 开发教程》（参考 18）

下面是业务协议示例，不是 eCAL 自动添加的字段：

```json
{
  "sourceId": "robot-1-front-camera",
  "bootId": "run-20261013-01",
  "sequence": 1024,
  "captureTimeNs": "1791849600000000000",
  "schemaVersion": 1,
  "frameId": "camera_front",
  "payload": "..."
}
```

本例的 `captureTimeNs` 约定为自 Unix 纪元（1970-01-01T00:00:00Z）起的纳秒数，在 JSON 中用十进制字符串表示，接收端按整数解析。采用 IEEE 754 双精度数的解析器无法精确表示超过 `2^53 - 1` 的所有整数；直接使用 JSON 数字可能丢失纳秒精度。《RFC 8259 第 6 节》（参考 19）

高频数据通常用二进制格式；JSON 可用于低频调试。协议中写清：尺寸上限、字节序、单位、坐标系、时间基准、版本兼容及未知字段处理。不要直接发送带指针、虚函数或平台相关布局的 C++ 对象内存。

多发布者和进程重启场景中，单个 `sequence` 不够：应与 `sourceId`、`bootId` 一起解释，避免把重启后的正常序号重置当成旧数据。

### 6.3、时间戳、时延与数据新鲜度

建议区分四个时刻：采集时间、发布时间、接收时间、处理完成时间。跨主机端到端时延计算需要先确定时钟同步误差；本机耗时测量优先采用单调时钟。

| 指标 | 说明 | 需要避免的误解 |
| --- | --- | --- |
| 吞吐 | 每秒有效数据量 | 峰值吞吐等于所有负载下的性能 |
| 时延 | 从指定起点到指定终点的时间 | `Send` 耗时等于端到端时延 |
| 抖动 | 时延或周期的波动 | 平均值正常代表尾部正常 |
| 数据年龄 | 当前时刻距离采集时刻的间隔 | 回调收到的数据必然足够新 |
| 丢帧 | 序号缺口与各环节丢弃计数 | 网络无丢包就没有业务丢帧 |

性能验收应固定载荷大小、频率、订阅者数、传输层、CPU 负载和测量边界，同时报告分位数与丢帧情况。官方 《性能测量说明》（参考 20） 可作为测试方法参考，结果不能直接替代本项目实测。

### 6.4、与 ROS 2 / DDS / Zenoh 的关系

eCAL 是通信库及工具，ROS 2 是更完整的机器人开发生态。官方介绍了通过 `rmw_ecal` 接入 ROS 的方向；实际使用前应核对具体 RMW 项目的维护情况、支持发行版及功能覆盖。《eCAL 与 ROS 的关系》（参考 21）

做架构比较时，可按下面几条问题判断：

- **与 DDS 比**：是否需要其特定实现提供的 History、Durability、Deadline、Liveliness 等 QoS？不能把这些名称原样套到 eCAL 的 SHM/TCP 配置上。
- **与 Zenoh 比**：是否需要跨网络路由，以及键空间上的查询与存储？eCAL Topic 和 Service 应分别建模，不能当成统一的 `put/get` 接口。
- **与 MQTT 比**：是否以公网设备接入、Broker 管理和消息交付流程为中心？这与同机大数据流水线是不同的需求。

这里比较的是设计维度，具体能力要按所选版本和插件核对。

### 6.5、安全与故障边界

对普通局域网配置，不应未经验证就假定它具备完整的身份认证、授权或加密边界。项目应明确可信网络范围，按需要采用网络隔离、受控网关或安全隧道，并限制录制与进程管理工具的使用权限。

数据接收侧仍需校验长度、字段和来源语义；控制指令携带有效期及去重 ID。网络断开时，执行侧应根据本地看门狗进入约定状态，不能仅依赖远端发一条「停止」消息。

## 第七章、看项目代码时，按这条路线走

以一个具体 Topic 或服务方法为线索，依次找：

| 顺序 | 在代码/配置中定位 | 想确认的问题 |
| --- | --- | --- |
| 1 | eCAL 依赖版本、CMake、动态库 | 实际编译和运行使用哪个版本？ |
| 2 | `ecal.yaml`、`ecal.ini`、`ECAL_DATA` | 配置从哪来？进程工作目录是什么？ |
| 3 | `Initialize`、`Finalize` | 初始化和退出顺序是否正确？ |
| 4 | Topic 常量、类型信息、消息定义 | 名称、载荷、单位和版本怎样约定？ |
| 5 | `CPublisher`、`Send` | 谁发布？在哪个线程？频率与帧大小？ |
| 6 | `CSubscriber`、接收回调 | 谁订阅？是否持有回调内存或阻塞？ |
| 7 | `layer`、`priority_network`、`zero_copy_mode` | 实际走哪层？两端设置是否匹配？ |
| 8 | `CServiceServer`、`CServiceClient` | 服务有哪些实例？超时和重试怎样处理？ |
| 9 | Recorder、Player、Sys 配置 | 哪些 Topic 被录制？回放如何隔离？ |
| 10 | 队列、序号、ack、看门狗 | 慢消费者、重启和断网时如何降级？ |

优先找到「Topic 名称构造」和「消息结构定义」，再追到发布与消费代码。填写下面这张表，通常比只看某个 `Send()` 更能说明系统：

| Topic / 服务方法 | 来源 -> 消费者 | 频率 / 帧大小 | 实际传输 | 队列 / 超时策略 | 协议与处理模块 |
| --- | --- | --- | --- | --- | --- |
|  | 传感器 -> 算法 |  |  |  |  |
|  | 算法 -> 可视化 |  |  |  |  |
|  | 控制端 -> 执行端 |  |  |  |  |
|  | 请求 -> 响应 |  | TCP |  |  |

### 7.1、配置到底加载了哪一份

6.x 自动查找配置时，先看 `ECAL_DATA`，再看进程工作目录，之后才是用户或系统目录。Windows 常见 `%LOCALAPPDATA%\eCAL\ecal.yaml`，Linux 常见 `~/.ecal/ecal.yaml` 与 `/etc/ecal/ecal.yaml`。《配置加载顺序》（参考 22）

排查「我改了配置为什么没生效」时，记录实际加载路径、启动参数和代码中的配置覆盖。还要确认进程已按所用版本要求重新启动或重新初始化。

### 7.2、C++ 示例：节点最小骨架

下面用 6.x 字符串接口展示初始化、订阅、发布与退出。它是便于阅读的演示骨架，`hello` 的处理应替换成项目自己的协议和有界队列；输出到终端只用于低频演示。《官方字符串示例》（参考 23）

```cpp
#include <ecal/ecal.h>
#include <ecal/msg/string/publisher.h>
#include <ecal/msg/string/subscriber.h>

#include <chrono>
#include <iostream>
#include <string>
#include <thread>

int main()
{
    // 1. 创建进程级上下文；传输策略由实际配置决定
    eCAL::Initialize("robot_demo");

    {
        // 2. 通信对象必须覆盖整个收发周期
        eCAL::string::CSubscriber sub("robot/1/demo/hello");
        eCAL::string::CPublisher pub("robot/1/demo/state");

        // 3. 回调数据不要以引用或裸指针形式交给异步线程
        sub.SetReceiveCallback(
            [](const eCAL::STopicId&,
               const std::string& message,
               long long,
               long long)
            {
                std::cout << "received: " << message << '\n';
                // 生产代码：校验 -> 复制/取得所有权 -> 有界队列
            });

        // 4. 周期状态让晚加入者能等到新样本；不代表保留历史
        unsigned long long sequence = 0;
        while (eCAL::Ok())
        {
            pub.Send("running, sequence=" + std::to_string(sequence++));
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
        }
    } // 5. Publisher/Subscriber 先销毁

    eCAL::Finalize(); // 6. 再关闭通信上下文
    return 0;
}
```

生产实现还应补上初始化/发送错误处理、退出信号、业务线程停止及回调资源同步。5.x 示例中的 `Initialize(argc, argv, ...)`、`AddReceiveCallback` 和旧回调参数不能直接混入此代码。

## 第八章、常见问题与排查顺序

| 现象 | 优先检查 | 常见原因 |
| --- | --- | --- |
| 同机能收，跨机不通 | 实际配置路径、`communication_mode`、注册网络 | 一方仍在 local 模式 |
| Monitor 看不到节点 | 注册层、网卡、多播、超时、版本 | 发现链路被防火墙或容器网络隔离 |
| 看得到 Topic，但没有样本 | 名称、两端可用层、数据端口、发布时机 | 注册链路通而数据链路不通 |
| 发布端开了 TCP 仍不通 | 订阅端 TCP 开关、发布侧优先级 | 双方没有选中共同可用的层 |
| 大帧偶发丢失 | 分片、缓冲区、突发流量、回调耗时 | 平均带宽低但瞬时流量过大 |
| 启用零拷贝后发送变慢 | 回调持锁时间、慢订阅者 | 省拷贝的同时增强了读写耦合 |
| 异步处理时偶发数据损坏 | 回调载荷生命周期、对象所有权 | 队列保存了已失效的引用或指针 |
| 服务发现了但调用失败 | 主机名解析、TCP 可达性、实例选择 | 发现成功但服务连接建立失败 |
| 新订阅者没有当前状态 | 状态发布周期、快照接口 | 把 pub/sub 当成 Retain |
| 录制缺 Topic 或漏帧 | 选择范围、录制节点、磁盘、队列、源频率 | Recorder 自身消费或写入能力不足 |
| 回放结果与现场不同 | 参数、标定、时间、实时源、外部依赖 | 输入环境不一致或算法存在非确定性 |
| 进程已启动但控制不可用 | 就绪条件、数据新鲜度、业务线程 | 把进程存在当成业务健康 |

建议的排查顺序是：**实际版本与配置 -> 注册发现 -> 具体 Topic/服务 -> 数据传输 -> 回调与队列 -> 业务结果**。每次只改变一个关键变量，保留前后频率、序号缺口和耗时记录。

## 第九章、面试高频问答

### 9.1、eCAL 和 MQTT 的核心区别是什么？

eCAL 无中心 Broker，重点是进程间及主机间通信，可以使用 SHM、UDP 和 TCP；MQTT 以客户端与 Broker 的消息交换为核心。选型时应先问是同机大数据流水线，还是围绕 Broker 的设备接入与消息管理。

### 9.2、eCAL 为什么同机传大图像比较有优势？

共享内存让进程间交换数据不必经过网络数据路径；收益取决于载荷大小、复制次数、序列化和同步成本。不能用某次峰值吞吐证明所有图像链路都快，更不能直接证明它具备硬实时保证。

### 9.3、使用共享内存就是零拷贝吗？

不是。普通 SHM 仍可能复制载荷，零拷贝需要相应配置和 API；序列化、混合传输与多缓冲也会影响具体路径。回答时应逐段解释数据从采集到消费经过哪些缓冲区。

### 9.4、改成 TCP 就不会丢数据了吗？

不能这样保证。TCP 处理链路内的可靠传输，但发送前、回调和业务队列仍可能遗漏消息，进程崩溃也可能导致动作结果丢失。关键业务需要独立的确认、去重与恢复策略。

### 9.5、为什么 Monitor 能看到 Topic，订阅者却收不到？

发现注册和业务数据是不同链路。应核对 Topic 名称、传输层交集、优先级、端点与回调，不能仅凭注册可见就排除网络问题。

### 9.6、为什么不能在回调里直接运行耗时算法？

回调占用接收处理资源，耗时计算会使后续数据来不及消费；零拷贝时还可能延长共享缓冲区被占用的时间。通常用回调完成校验和所有权交接，由业务线程执行计算，并明确队列满时怎样处理。

### 9.7、pub/sub 和服务分别适合什么场景？

持续产生的数据用 pub/sub；一次性读取或执行并取得响应用服务。长任务最好分成受理、进度和终态；服务调用超时不意味着任务没有执行，重试仍要考虑幂等。

### 9.8、Recorder/Player 和消息持久化有什么区别？

Recorder/Player 面向数据采集与重新发布，普通 Subscriber 不会因此自动拥有离线历史补发。业务恢复、任务状态与消息确认需要另外设计；回放也必须控制 Topic 范围和现场隔离。

## 第十章、外部链接参考

以下按正文首次引用顺序汇总外部参考资料；相同网址合并为一项，正文中的参考编号与本章对应。

1、eCAL 6 迁移指南：[https://eclipse-ecal.github.io/ecal/stable/versions/6.0/migration_guide.html](https://eclipse-ecal.github.io/ecal/stable/versions/6.0/migration_guide.html)

2、官方项目介绍：[https://github.com/eclipse-ecal/ecal](https://github.com/eclipse-ecal/ecal)

3、服务通信说明 / 服务教程：[https://eclipse-ecal.github.io/ecal/stable/getting_started/services.html](https://eclipse-ecal.github.io/ecal/stable/getting_started/services.html)

4、网络配置教程：[https://eclipse-ecal.github.io/ecal/stable/getting_started/network.html](https://eclipse-ecal.github.io/ecal/stable/getting_started/network.html)

5、Docker 教程：[https://ecal.novacodes.de/advanced/tutorials/ecal_in_docker/](https://ecal.novacodes.de/advanced/tutorials/ecal_in_docker/)

6、传输层说明：[https://eclipse-ecal.github.io/ecal/stable/advanced/transport_layers.html](https://eclipse-ecal.github.io/ecal/stable/advanced/transport_layers.html)

7、TCP 配置说明：[https://eclipse-ecal.github.io/ecal/stable/advanced/layers/tcp.html](https://eclipse-ecal.github.io/ecal/stable/advanced/layers/tcp.html)

8、运行时配置示例：[https://eclipse-ecal.github.io/ecal/stable/getting_started/howto/configuration.html](https://eclipse-ecal.github.io/ecal/stable/getting_started/howto/configuration.html)

9、消息丢失说明：[https://eclipse-ecal.github.io/ecal/stable/advanced/message_drops.html](https://eclipse-ecal.github.io/ecal/stable/advanced/message_drops.html)

10、零拷贝机制说明：[https://eclipse-ecal.github.io/ecal/stable/advanced/layers/shm_zerocopy.html](https://eclipse-ecal.github.io/ecal/stable/advanced/layers/shm_zerocopy.html)

11、SHM 层说明：[https://eclipse-ecal.github.io/ecal/stable/advanced/layers/shm.html](https://eclipse-ecal.github.io/ecal/stable/advanced/layers/shm.html)

12、Monitor 教程：[https://eclipse-ecal.github.io/ecal/stable/getting_started/monitor.html](https://eclipse-ecal.github.io/ecal/stable/getting_started/monitor.html)

13、录制入门：[https://ecal.novacodes.de/getting_started/6-applications/6_2_recorder/](https://ecal.novacodes.de/getting_started/6-applications/6_2_recorder/)

14、录制架构：[https://ecal.novacodes.de/using_ecal/applications/ecal-rec/ecal_rec_architecture/](https://ecal.novacodes.de/using_ecal/applications/ecal-rec/ecal_rec_architecture/)

15、Player 教程：[https://eclipse-ecal.github.io/ecal/stable/getting_started/player.html](https://eclipse-ecal.github.io/ecal/stable/getting_started/player.html)

16、Sys 教程：[https://eclipse-ecal.github.io/ecal/stable/getting_started/sys.html](https://eclipse-ecal.github.io/ecal/stable/getting_started/sys.html)

17、线程模型说明：[https://eclipse-ecal.github.io/ecal/stable/advanced/threading_model.html](https://eclipse-ecal.github.io/ecal/stable/advanced/threading_model.html)

18、pub/sub 开发教程：[https://eclipse-ecal.github.io/ecal/v6.1/getting_started/howto/pubsub.html](https://eclipse-ecal.github.io/ecal/v6.1/getting_started/howto/pubsub.html)

19、RFC 8259 第 6 节：[https://www.rfc-editor.org/rfc/rfc8259#section-6](https://www.rfc-editor.org/rfc/rfc8259#section-6)

20、性能测量说明：[https://eclipse-ecal.github.io/ecal/stable/advanced/performance.html](https://eclipse-ecal.github.io/ecal/stable/advanced/performance.html)

21、eCAL 与 ROS 的关系：[https://eclipse-ecal.github.io/ecal/stable/advanced/ros_comparison.html](https://eclipse-ecal.github.io/ecal/stable/advanced/ros_comparison.html)

22、配置加载顺序：[https://eclipse-ecal.github.io/ecal/stable/configuration/options.html](https://eclipse-ecal.github.io/ecal/stable/configuration/options.html)

23、官方字符串示例：[https://eclipse-ecal.github.io/ecal/stable/getting_started/howto/pubsub/string_hello_world.html](https://eclipse-ecal.github.io/ecal/stable/getting_started/howto/pubsub/string_hello_world.html)
