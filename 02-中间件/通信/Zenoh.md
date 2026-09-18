# Zenoh：分布式通信中间件扫盲、代码阅读与面试准备

> 目标：理解 Zenoh 的通信模型和它与 MQTT/DDS 的边界；能在机器人、车载或边缘项目中快速定位会话建立、订阅、发布、查询与网络配置代码；能清楚回答常见面试问题。
>
> 核心结论：**Zenoh 把「发布/订阅」「分布式查询」「存储」统一在同一套键空间（Key Expression）上。它不要求必须有中心 Broker：节点之间可以直连组网（peer），也可以经由 Router 转发（client）；同一个键既能被订阅，也能被 `get` 查询到存储值或现算结果。**

## 第一章、Zenoh 是什么，以及为什么选它

### 1.1、先用一张图理解

```text
  传感器节点（peer）                          算法节点（peer）
     Session                                     Session
        |  put robot/1/lidar/scan                    ^  
        |                 subscribe robot/1/lidar/** |
        |                                            |
        +== 路径1：同网段直连 =========================+
        |                                            |
        |  路径2：经 Router 转发                      |
        v                                            |
 +-----------------------------------------------------+
 |                   Router（可选）                    |
 |  转发、跨网段互联、（可）承载 Storage、DDS/MQTT 桥接   |
 +-----------------------------------------------------+
        ^                                             |
        |  get robot/1/config/**                reply v  
        |                                             |
      运维 / 云端（client）<-------------------------+
```

两条路径二选一，取决于双方是否同网段可直连：路径①可走 TCP/UDP/QUIC/TLS/串口等链路；路径②为左侧主干下行至 Router、再由 Router 经右侧主干上行到订阅方。`reply` 同样由 Router 转发，真正回答的是某个节点上的 Queryable 或某处配置的 Storage。

同主机的大块数据还可在已建立的传输之上启用**共享内存（SHM）** 承载载荷。SHM 不是独立的 endpoint 类型（没有 `shm://` 这类地址），控制面仍走上面那些链路，且需要两端都启用支持。

与 MQTT 最大的差别有两点：

1. **中间件不是必需的中心节点。** 同一网段内的 peer 可以通过 scouting（多播/gossip）互相发现并直连，Router 只是在「需要跨网段转发、需要集中汇聚或桥接」时才引入的角色。Storage 常挂在 Router 上，但并非只能挂在 Router 上（见 5.1）。
2. **同一个键有两种访问方式。** 订阅者拿到的是「此刻起新发生的数据」，`get` 拿到的是「现在谁能回答这个键」——可能是 Storage 里保存的值，也可能是某个 Queryable 现算的结果。

### 1.2、为什么机器人/边缘项目会选 Zenoh

| 需求 | Zenoh 的对应能力 | 典型例子 |
| --- | --- | --- |
| 局域网内低时延、高吞吐 | peer 直连，不必经过中心节点；支持共享内存传输 | 同机/同网段的点云、图像传输 |
| 跨网段、跨云边 | Router 级联、可配置路由与作用域 | 车端 ↔ 边缘 ↔ 云 |
| 既要流数据又要查当前值 | pub/sub 与 query 共用键空间，Storage 可保存并回答 | 新节点上线后先订阅、再 `get` 当前状态 |
| 弱网/受限设备 | Zenoh-Pico 面向 MCU；支持串口等非 IP 链路 | MCU 经串口接入机器人网络 |
| 与既有生态互通 | DDS/ROS 2、MQTT、REST 等桥接插件 | ROS 2 跨网段通信 |
| 资源可控 | 可靠性、拥塞控制、优先级按发布点分别配置 | 控制指令高优先级，日志低优先级 |

Zenoh 不是「更快的 MQTT」这么简单，也不是万能替代品。它没有 MQTT 那种面向公网海量设备、被广泛实现的成熟 Broker 生态与账号体系；如果项目只是「大量 MCU 通过公网上报状态到云平台」，MQTT 往往更省事。Zenoh 的优势集中在**局域网/边缘的高性能数据面、多协议互通，以及 pub/sub + query + storage 的统一抽象**。

## 第二章、核心概念与键空间设计

### 2.1、关键名词

| 名词 | 含义 | 看代码时常见名字 |
| --- | --- | --- |
| Session（会话） | 应用接入 Zenoh 网络的入口，承载所有原语 | `zenoh::open(config)`（Rust）、`Session::open(config)`（C++） |
| Key Expression（键表达式） | 数据的命名与路由依据，层级用 `/` 分隔 | `robot/{id}/lidar/scan` |
| Publisher / put | 向某个键写入数据 | `session.put(key, payload)`、`declare_publisher` |
| Subscriber | 声明对某组键的兴趣，收到后续样本 | `declare_subscriber` |
| Queryable | 声明「我能回答这组键的查询」 | `declare_queryable` |
| get / Selector | 发起一次分布式查询并收集回复 | `session.get("k/**?arg=1")` |
| Sample | 一条数据：键、载荷、类型（PUT/DELETE）、编码、时间戳等 | `sample.key_expr()`、`sample.payload()` |
| Storage | 由加载 `storage-manager` 插件的节点提供，按键规则缓存/持久化数据并回答 `get` | `storage-manager`、volume |
| 模式：peer / client / router | 节点在网络中的角色 | `mode: "peer"` |

注意：**Key Expression 是命名空间，不是队列名，也不是节点地址。** 谁能收到、谁来回答，取决于当前网络里声明了哪些订阅和 Queryable，以及 Router 的路由与访问控制配置。

### 2.2、先分清「流、状态、事件、命令、可查询资源」

一个实用的机器人项目约定如下（具体项目以实际协议为准）：

```text
robot/{id}/lidar/scan            高频点云/扫描流
robot/{id}/state/pose            位姿
robot/{id}/state/battery         低频状态
robot/{id}/event/fault           一次性事件
robot/{id}/cmd/velocity          下发控制
robot/{id}/cmd/ack               命令执行结果
robot/{id}/config/**             以 get 为主的可查询配置资源
robot/{id}/liveliness            存活性标记
```

| 类型 | 语义 | 常见配置 | 例子 |
| --- | --- | --- | --- |
| 高频流 stream | 后值天然覆盖前值，允许丢 | BestEffort + 拥塞丢弃 + 低优先级 | 点云、图像、里程计 |
| 状态 state | 需要新上线者也能拿到 | Reliable + Storage 保存最新值 | 电量、模式、在线状态 |
| 事件 event | 一次性事实，不能当状态 | Reliable，不进「只存最新值」的 Storage | 故障、碰撞、按键 |
| 命令 cmd | 可能重发，必须幂等 | Reliable + 高优先级 + `requestId` | 速度指令、任务下发 |
| 可查询资源 | 由 Queryable 现算或 Storage 回答 | 以 `get` 为主 | 参数表、地图片段、诊断快照 |

配置的**写入路径要单独约定**：Queryable 不会收到 `put`。若云端通过 `put robot/{id}/config/<item>`（具体键，不带通配符）向 `robot/{id}/config/**` 这段键空间下发配置，设备必须同时订阅该键空间（或由 Storage 承载），否则数据无处落地——这正是 5.1 节「put 了却 get 不到」的典型成因。本文示例中 Queryable 只负责回答当前值。

### 2.3、通配符

Zenoh 键表达式中：`*` 匹配**一个**层级（chunk），`**` 匹配**零个或多个**层级，`$*` 用于层级内部的部分匹配。例如：

```text
robot/*/state/battery        // 匹配任意一个 robot id
robot/1/**                   // 匹配 robot/1 及其下所有层级
robot/1/state/*              // 只匹配 state 下一层
demo/example/zenoh$*         // 层级内前缀匹配
```

规范上键表达式不以 `/` 开头或结尾，也不含空 chunk；库通常要求「规范形式（canonical form）」，不规范的写法会被拒绝或需要显式转换（具体行为以所用版本的 API 文档为准）。

与 MQTT 不同的是：**Zenoh 的通配符不仅能用于订阅，也能用于 `get` 的 Selector，某些场景下还能用于 `delete`。** 但发布一条具体数据时应使用不含通配符的确定键，否则「这条数据究竟写到哪个键」在语义上就不成立。线上节点同样不应随意订阅 `**`：会放大流量，也难以做最小权限控制。

## 第三章、组网与收发链路

### 3.1、从建会话到收发

```text
应用                                   Zenoh 网络
  | ---- 读取配置（mode / endpoints / scouting）
  | ---- open(config) ------------------------> |  建立 Session
  |        scouting：多播 / gossip 发现对端      |
  |        connect：主动连到 tcp/host:7447 等    |
  |        listen：被动监听本地端点              |
  | <--- Session 就绪 ------------------------- |
  | ---- declare_subscriber(key) -------------> |  声明兴趣，路由随之更新
  | ---- declare_queryable(key) --------------> |  声明「我能回答」
  | ---- declare_publisher(key) --------------> |  预解析键，后续 put 更省开销
  | ---- put(key, payload) -------------------> |  按当前订阅关系路由
  | <--- subscriber callback ------------------ |  收到他人发布的样本
  | ---- get(selector) -----------------------> |  分布式查询
  | <--- reply * N ---------------------------- |  多个 Queryable/Storage 各自回复
  | ---- close() ------------------------------>|
```

代码中通常不会手写协议报文，由 Zenoh 库完成；业务代码要处理的是：**配置从哪来、用什么模式组网、声明了哪些键、回调里做什么、发布时的可靠性与拥塞策略、以及网络变化时的行为**。

### 3.2、三种模式

| 模式 | 行为 | 适用场景 |
| --- | --- | --- |
| peer | 与其他 peer 直连组网，可多播发现，去中心 | 同网段的机器人内部节点、车内域控 |
| client | 只与一个对端（通常是 Router，也可以是某个 peer）建立会话，由它代为路由；配置多个端点时是候选列表，按顺序尝试直到连上其中一个 | 资源受限设备、跨网段接入、云端工具 |
| router | 转发流量、级联其他 Router、承载 Storage 与桥接插件 | 边缘网关、跨网段汇聚点 |

`peer` 不等于「一定不需要 Router」，`client` 也不等于「一定走公网」。真正决定连通性的是配置里的 `connect`/`listen` 端点与 `scouting` 开关。**排查连通问题时，先确认三件事：模式、端点、多播是否被网络设备拦截。**

### 3.3、发现、重连与状态机

Zenoh 的连通性由三部分决定：scouting（UDP 多播发现与 gossip 转发）、显式 `connect` 端点、显式 `listen` 端点。默认的 scouting 多播地址为 `udp/224.0.0.224:7446`（IPv6 环境为 `[ff24::224]:7446`），REST 插件默认 `8000`。端口上要注意：**Router 默认监听 `tcp/[::]:7447`，这也是 `connect` 的默认目标端口；peer 默认监听的是随机端口（`tcp/[::]:0`），其真实端口经 scouting/gossip 通告出去。** 因此在有防火墙的环境里做 peer 直连，只放行 7447 是不够的，要么显式配置固定的 `listen` 端点，要么放行相应端口范围。库通常内置了对已配置端点的自动重连与退避；**但「Session 还在」不等于「对端还在」。**

建议把连接与业务解耦，做成事件驱动的状态机：

```text
INIT -> 读取配置 -> OPENING -> SESSION_READY -> DECLARING -> 上线标记与状态同步 -> RUNNING
          ^            |                          |
          |            +---- 打开失败 ----+       +---- 声明失败 ----+
          |                               |                          |
          +--------- 退避重试 <-----------+--------------------------+

RUNNING --对端消失（liveliness / matching / 超时无数据）--> 降级或本地兜底
降级或本地兜底 --等待恢复--> 重新同步 --> RUNNING
```

关键点：

- **不要把 `open()` 成功当作「可以收发了」。** 订阅和 Queryable 的声明需要在网络中传播，刚声明就立刻 `get` 可能拿不到回复；同理，刚 `open` 就 `put`，此刻可能还没有任何订阅者。
- 需要确认「确实有人在听」时，用 **matching status / matching listener**（发布侧可感知是否存在匹配的订阅者）或 liveliness，而不是靠 `sleep`。
- 对端消失的检测优先用 liveliness 或应用层心跳，而不是依赖底层 TCP 超时。
- 自行实现重连逻辑时，同样使用「指数退避 + 随机抖动 + 最大间隔」，避免大面积断网后集体冲击 Router。

## 第四章、可靠性、拥塞控制与优先级：没有 MQTT 那样的 QoS 0/1/2

这是 MQTT 出身的人最容易搞混的一节。Zenoh 没有「QoS 1 = 至少一次、由接收端回 PUBACK」这种端到端应用级确认，而是把可靠性拆成了几个正交的旋钮：

| 旋钮 | 取值 | 含义 |
| --- | --- | --- |
| Reliability | Reliable（默认）/ BestEffort | 传输通道上的标记/选路提示；当前实现并不因此触发丢包重传，可能被用于选路（如可靠数据倾向走 TCP、尽力而为数据可走 UDP），不是端到端业务确认 |
| Congestion Control | Drop（默认）/ Block，部分版本还提供 BlockFirst | 发送队列满时，直接丢弃这条数据还是阻塞调用者；BlockFirst 只阻塞到首个分片入队，折中吞吐与整条丢弃 |
| Priority | RealTime … Background 多档，默认 Data | 拥塞时谁先发、谁先被丢 |
| Express | 开 / 关（默认关） | 是否跳过批处理立即发送，降时延但降吞吐 |

默认值随版本可能微调，以所用版本文档为准。注意「不配置 = BestEffort」是常见误解：**不配置时是 Reliable。** 高频流要拿到 BestEffort 必须显式指定。

**关键理解：Reliable 目前主要是传输链路上的标记/选路提示，并不代表数据丢失后会被自动补发，更不是「对端应用一定处理了这条消息」。** 中间节点队列溢出（Drop 策略）、订阅者尚未声明、节点尚未连通、进程崩溃，都会让数据到不了业务层。

因此与 MQTT 相同的结论成立：**有副作用的控制指令必须自己做幂等和确认。** 推荐做法是命令携带 `requestId`，执行侧记录已处理的 ID，并通过 `cmd/ack` 回一条结果；发起侧超时未收到 ack 就重发，接收侧重复到达时只返回之前的结果，不重复执行动作。

高频流数据则相反：`BestEffort + Drop + 较低优先级` 通常比「什么都开 Reliable」更健康——否则一个慢消费者可能通过 Block 把发布侧拖死。

## 第五章、Storage、Liveliness 与几个易混机制

| 机制 | 解决什么问题 | 大致对应 MQTT 的 | 注意点 |
| --- | --- | --- | --- |
| Storage | 让键上的数据能被后来者 `get` 到 | Retained Message（但更强） | 需在承载节点上配置插件与 volume；键范围、是否只存最新值都要显式配置 |
| Liveliness Token | 声明「我还活着」，对端可订阅其出现与消失 | LWT + 在线状态 | 进程退出或链路断开时 token 自动消失 |
| Advanced Publisher / Subscriber | 缓存历史、检测漏样本并请求重传 | 持久会话 + 离线补发 | 属于上层能力，需两端都启用；配置项随版本演进 |
| Attachment | 随样本附带元数据，不污染业务载荷 | MQTT 5 User Property | 适合放 trace id、序号、版本 |
| Timestamp | 样本时间戳，用于排序与冲突解决 | —— | 通常需要在配置中启用 timestamping |

### 5.1、Storage 与 MQTT Retain 的区别

Retain 是「每个 Topic 保存最后一条」，能力固定；Zenoh Storage 是一个**可配置的插件**（`storage-manager`）：你指定它负责哪一段键空间、用哪个 volume（内存、RocksDB、文件系统、时序库等）、是否只保留最新值、是否参与副本对齐。它最常挂在 `zenohd` 上，但 `zenohd` 本身也可以跑在 peer 模式，应用进程同样可以加载该插件——**「必须有 Router 才能有 Storage」是误解**。

代价是：**它不会自动存在。**「我 put 了数据，为什么新节点 get 不到」最常见的原因，就是这段键空间根本没有配置 Storage，也没有任何 Queryable 在回答。

第二个常见原因是没有启用 `timestamping`：Storage 依赖样本时间戳做去重与副本对齐，未打时间戳的样本可能被直接忽略，表现就是「配了 Storage 却仍然 get 不到」。

### 5.2、Liveliness 与正常退出

Liveliness Token 的语义比自己发一条 `online=false` 更可靠：它随会话/链路存在而存在，进程被 kill、掉电、网络断开时都会消失，订阅 liveliness 的一方会收到「消失」通知。常见模式是：

```text
上线：declare_liveliness_token("robot/1/liveliness")
运行：token 持续存在，监控端订阅 liveliness 变化
下线 / 崩溃 / 断网：token 自动消失，监控端立即感知
```

如果还需要知道「离线原因」，再配合一条普通的 event 消息即可；不要用普通 put 去替代 liveliness 做存活检测。

## 第六章、业务实现要点

### 6.1、收到数据后的推荐路径

```text
Subscriber 回调（尽快返回）
        |
        v
校验键、载荷长度、编码（Encoding）、来源与权限上下文
        |
        v
反序列化（JSON / CDR / Protobuf / 自定义二进制）
        |
        v
投递到业务队列（不要在回调内做耗时计算或阻塞 I/O）
        |
        v
业务任务执行 -> 更新真实状态 -> put(state) / put(ack)
```

Zenoh 的回调通常运行在库的内部线程上（也可选择基于 channel 的拉取式接口）。在回调里做重计算、阻塞等待锁或同步 I/O，会拖慢整条接收链路，甚至因为拥塞策略导致上游丢数据。**回调只做校验和投递，业务线程执行实际工作**，这条经验与 MQTT 完全一致。

### 6.2、载荷与编码

Zenoh 的载荷是字节序列，协议本身不解释结构，但 Sample 上带有 `Encoding` 字段。**请把 Encoding 当成协议约定的一部分认真填写**，它是跨语言、跨团队调试时最省事的自描述信息：

```json
{
  "requestId": "a1b2c3",
  "ts": 1720000000,
  "type": "set_velocity",
  "params": { "vx": 0.5, "wz": 0.0 },
  "version": 1
}
```

JSON 便于调试；高频大数据（点云、图像）应使用二进制序列化，并优先评估**共享内存（SHM）零拷贝载荷**——同主机的大块数据可显著降低拷贝开销，但需要两端都启用支持，且对载荷生命周期有额外要求。

同样需要在协议文档里写清：必选字段、单位、时间戳来源、错误码、最大长度、未知字段处理规则以及版本演进策略。

### 6.3、什么时候用 get 而不是 subscribe

这是 Zenoh 相对 MQTT 多出来的一个设计维度：

| 场景 | 推荐 | 理由 |
| --- | --- | --- |
| 持续变化的数据流 | subscribe | 推送语义，无需轮询 |
| 节点刚启动，要拿当前值 | get（配合 Storage 或 Queryable） | 一次性获取快照，不必等下一次发布 |
| 参数表、地图、诊断信息 | get + Queryable | 按需现算，避免持续广播 |
| 既要快照又要增量 | 先 `declare_subscriber` 再 `get`，或使用 Advanced Subscriber 的历史能力 | 订阅先生效才不会漏更新 |

**顺序很重要：先声明订阅，再发起 `get`。** 订阅先生效可保证两次调用之间的更新不会丢失；快照与增量重叠的部分，用**递增的版本号或样本时间戳**去重，接收侧只接受更新的版本：

```json
{
  "mode": "auto",
  "battery": 82,
  "stateVersion": 1024,
  "ts": 1720000000
}
```

反过来先 `get` 再 `subscribe`，两次调用之间的更新会被永久丢失——版本号只能让你**发现**漏了一拍，不能把那条数据补回来。

### 6.4、与 ROS 2 / DDS 的关系

Zenoh 在机器人领域经常以两种形态出现：作为 ROS 2 的 RMW 实现直接承载 ROS 2 通信，或作为桥接把既有 DDS 网络接入 Zenoh 网络以实现跨网段互联。两种形态下 ROS 2 的 topic/service 都会被映射到 Zenoh 的键空间，映射规则由具体版本的实现定义。

阅读这类项目时要先确认：**当前是「ROS 2 直接跑在 Zenoh 上」还是「DDS + 桥接」**。两者排查路径不同——前者看 RMW 与 Zenoh 配置，后者还要看 DDS 的域 ID、QoS 以及桥接的映射与白名单配置。

### 6.5、Zenoh-Pico：MCU 侧的子集

嵌入式项目里接入 Zenoh 的通常不是完整实现，而是 **Zenoh-Pico**：面向 MCU 与 RTOS（FreeRTOS、Zephyr、ESP-IDF、Arduino、裸机等）的轻量实现。使用时要注意：

- 功能是**子集**：完整版的 Storage、插件、路由能力通常不在其中；支持的原语、模式（client / 多播 peer）与传输（TCP、UDP、串口等）随版本与平台而变。
- 资源受限：任务栈、缓冲区大小、最大分片长度、并发订阅数都要按平台裁剪，不能照抄示例配置。
- 线程模型可选：有的构建提供后台读任务与租约任务，有的需要应用自行周期性驱动（read / lease）。**这一点搞错会表现为「能连上但收不到数据」或「运行一段时间后掉线」。**
- 与桌面端互通时，务必确认两端版本的协议兼容性。

具体能力清单以所用版本的官方文档为准，不要沿用旧版本的经验。

### 6.6、安全：默认配置通常不是生产配置

1. 传输层使用 TLS/QUIC 并校验证书链；需要双向认证时启用 mTLS，不要为了「先连上」长期关闭校验。
2. 启用访问控制（ACL）：按节点限制可读、可写、可查询的键空间，遵循最小权限。例如某设备只能写 `robot/1/state/**`、`robot/1/event/**`、`robot/1/cmd/ack`，只能读 `robot/1/cmd/velocity` 等下行命令键，并只对 `robot/1/config/**` 提供查询回答。注意 `cmd/**` 里既有下行命令也有上行 ack，不要整段划成同一种权限。另外还要允许设备在 `robot/1/liveliness` 上声明 liveliness token、允许监控端订阅其变化——声明 token 属于与 put/get 相互独立的一类动作，漏配会让存活检测直接失效。
3. 谨慎对待多播 scouting：在不可信网络中关闭自动发现，改为显式配置端点，避免任意节点加入网络。
4. Router 暴露的管理、REST 等插件端口不应直接对公网开放。
5. 载荷不能因为走了 TLS 就完全信任：仍要校验长度、字段范围、命令来源语义和重复请求。
6. 日志中不要打印密钥、证书私钥或敏感载荷。

## 第七章、看项目代码时，按这条路线走

以一个具体的键（某个状态或某条命令）为线索，依次找：

| 顺序 | 在代码/配置中搜索 | 想确认的问题 |
| --- | --- | --- |
| 1 | `zenoh`、`config`、`json5`、`7447`、`7446`、`224.0.0.224` | 用哪个语言绑定和版本？配置来自文件还是代码？ |
| 2 | `mode`、`connect`、`listen`、`scouting`、`multicast` | 是 peer 还是 client？连谁？是否依赖多播发现？ |
| 3 | `open`、`session` | 会话在哪创建？生命周期多长？是否全局单例？ |
| 4 | `declare_subscriber`、`callback`、`recv` | 订阅哪些键？回调里做了什么？是否阻塞？ |
| 5 | `put`、`declare_publisher`、`delete` | 谁在发布？发布什么键？载荷格式与 Encoding？ |
| 6 | `reliability`、`congestion`、`priority`、`express` | 各发布点的策略是否与数据特性匹配？ |
| 7 | `get`、`queryable`、`selector`、`reply` | 哪些数据走查询？谁来回答？一致性与超时怎么设？ |
| 8 | `storage`、`volume`、`plugin`、`bridge` | 哪些节点（Router、peer 或应用进程）加载了 `storage-manager`？配了哪些 Storage 与桥接？覆盖哪段键空间？ |
| 9 | `liveliness`、`matching`、`timeout` | 存活性与「对端是否存在」如何判断？ |
| 10 | `tls`、`cert`、`acl`、`auth` | 是否启用加密与访问控制？凭据如何管理？ |

**优先找到「键表达式的构造函数或常量定义」和「业务消息结构体」**，它们通常比单个 `put()` 调用更能说明协议约定。把实际观察到的键、方向、可靠性、优先级、载荷样例填进下表：

| Key Expression | 方向 | Reliability | Congestion / Priority | 载荷 / 触发条件 | 处理模块 |
| --- | --- | --- | --- | --- | --- |
|  | 设备 -> 云 |  |  |  |  |
|  | 云 -> 设备 |  |  |  |  |
|  | get / reply |  |  |  |  |

### 7.1、伪代码：节点最小骨架

```cpp
// 1. 建会话：配置决定组网方式，不要把端点硬编码在业务里
auto config  = zenoh::Config::from_file("zenoh.json5");
auto session = zenoh::Session::open(std::move(config));

// 2. 声明存活性标记：进程异常退出时自动消失
auto token = session.liveliness_declare_token("robot/1/liveliness");

// 3. 订阅命令：只订阅下行命令键，避免收到本节点发出的 cmd/ack
//    （同一会话内的发布默认也会投递给本会话的订阅者）
auto sub = session.declare_subscriber("robot/1/cmd/velocity",
    [](const zenoh::Sample &sample) {
        Command cmd;
        if (parse_command(sample.get_payload(), &cmd) == 0) {
            command_queue_push(cmd);   // 不在回调内操作硬件
        }
    });

// 4. 高频流：预声明 Publisher，按数据特性选择策略
auto scan_pub = session.declare_publisher("robot/1/lidar/scan",
    { .reliability = BEST_EFFORT, .congestion_control = DROP, .priority = DATA_LOW });

// 5. 提供可查询资源：让后来者不必等下一次发布
auto qbl = session.declare_queryable("robot/1/config/**",
    [](const zenoh::Query &query) {
        // 回复键必须是确定键（不含通配符），逐条回答与 selector 匹配的配置项
        for (const auto &item : current_config_items()) {   // item.key 形如 robot/1/config/max_speed
            query.reply(item.key, item.bytes);
        }
    });

// 6. 业务线程执行动作并回执
void control_task() {
    for (;;) {
        Command cmd = command_queue_pop();
        Result r = apply_command_idempotently(cmd);   // 按 requestId 去重
        session.put("robot/1/cmd/ack", encode(r));
        session.put("robot/1/state/pose", read_real_state());
    }
}
```

真实 API 名称随语言绑定（Rust / C / C++ / Python / Pico）和版本不同，但这段代码表达的职责边界应当成立：配置与会话负责组网，键的声明集中管理，回调只做轻量分发，业务线程执行动作并以真实状态上报。

## 第八章、常见问题与排查顺序

| 现象 | 优先检查 | 常见原因 |
| --- | --- | --- |
| 两个节点互相发现不了 | 模式、`connect`/`listen`、多播是否被交换机/防火墙/容器网络拦截 | 跨网段却依赖多播 scouting；容器未用 host 网络 |
| 能连上但收不到数据 | 键表达式是否真的匹配、通配符位置、订阅是否声明成功 | 发布键与订阅过滤器差一层；发布时机早于订阅传播 |
| 偶尔丢数据 | Reliability、Congestion Control、优先级、消费者速度 | BestEffort + Drop 下的正常行为；或回调阻塞导致积压 |
| 发布侧卡住不返回 | Congestion Control 是否为 Block、下游是否消费不过来 | Block 策略下队列满即阻塞调用线程 |
| get 没有任何回复 | 该键空间是否有 Storage 或 Queryable、超时设置、一致性参数 | 只 put 过数据但没配 Storage，自然无人回答；或配了 Storage 但未启用 timestamping，样本没被收下 |
| get 收到多条重复或冲突结果 | 是否有多个 Queryable/Storage 回答同一键、consolidation 配置 | 分布式查询本就可能多方回复，需按时间戳/版本取舍 |
| 节点崩溃后对端不感知 | 是否使用 liveliness、是否只靠 TCP 超时 | 用普通消息做心跳且间隔过长 |
| ROS 2 跨网段不通 | 是 RMW 直连还是 DDS 桥接、域 ID、键映射、桥接白名单 | 把两种形态的排查方法混用 |

排查时至少记录：节点模式、端点配置、Zenoh 版本、键表达式、方向、可靠性/拥塞/优先级、样本时间戳，以及网络拓扑（是否经 Router）。抓包或日志中要避免泄漏凭据和业务敏感信息。

## 第九章、面试高频问答

### 9.1、Zenoh 和 MQTT 的核心区别是什么？

MQTT 必须有 Broker，所有流量经中心节点，只有 pub/sub 一种语义，Topic 上的「历史」只有 Retain 这一种固定能力。Zenoh 允许 peer 直连去中心组网，Router 是可选角色；并且把 pub/sub、分布式 query 和 storage 统一到同一个键空间上，同一个键既可订阅也可查询。代价是生态成熟度、公网设备接入的现成方案不如 MQTT，配置项也更多。

### 9.2、Zenoh 的 Reliable 等价于 MQTT 的 QoS 1 吗？

不等价。Reliable 目前是传输链路上的标记/选路提示，当前实现并不会因此触发丢包重传，更不是端到端的应用确认；中间节点按拥塞策略丢弃、对端进程崩溃等情况仍会让数据到不了业务层。要做到「至少一次」的业务语义，需要应用层自己实现 `requestId` + ack + 超时重发 + 幂等。

### 9.3、Storage 和 MQTT 的 Retain 有什么区别？

Retain 是协议内置的「每个 Topic 存最后一条」；Zenoh Storage 是可在任意加载 `storage-manager` 插件的节点上配置的能力（典型是 `zenohd`），可以指定它负责的键空间、后端存储介质、是否只保留最新值，还能参与副本对齐。能力更强，但**必须显式配置**；不配 Storage 时，只有恰好有 Queryable 在回答该键空间，`get` 才会有结果，单纯 `put` 过的数据是取不到的。

### 9.4、peer 模式和 client 模式怎么选？

同网段、节点数可控、要求低时延且希望去中心时用 peer；资源受限、需要跨网段接入、或希望由网关集中管理路由与安全策略时用 client。两者的区别在于是否自行与其他节点建立直连，实际连通性仍取决于 `connect`/`listen`/`scouting` 的配置。

### 9.5、什么时候用 get，什么时候用 subscribe？

持续变化的数据流用 subscribe；「我现在想知道当前值是多少」「我想按需取一份参数或诊断信息」用 get。新节点启动时的正确组合是**先 `declare_subscriber` 再 `get`**：订阅先生效，两次调用之间的更新才不会丢失，快照与增量重叠的部分用版本号或时间戳去重；反过来先 `get` 再 `subscribe` 会留下无法补回的空窗。

### 9.6、为什么不要在订阅回调里做耗时操作？

回调运行在库的内部线程上，耗时计算或阻塞 I/O 会拖慢整条接收链路，导致队列积压：在 Drop 策略下表现为丢数据，在 Block 策略下可能把上游发布线程一起拖住。正确做法是回调只校验并投递到队列，由业务线程执行实际工作。

### 9.7、Liveliness 比自己发心跳好在哪？

Liveliness Token 的存在性由会话和链路本身维系，进程被 kill、掉电、网络断开时它会自动消失，订阅方能立即感知，且不占用周期性带宽。自己发心跳则受心跳间隔限制，检测延迟至少是一个周期，还要额外处理「最后一条心跳是不是遗留状态」的问题。

## 第十章、复习清单与项目信息补全

### 10.1、复习清单

- 能画出 peer 直连与经 Router 转发两种数据流，并说明 scouting 的作用。
- 能写出键表达式的通配符规则，并说明 `*` 与 `**` 的区别。
- 能解释 Reliability / Congestion Control / Priority 三者正交，且都不等于业务级「至少一次」。
- 能区分 pub/sub 与 get/queryable 的适用场景，并说明先 get 后 subscribe 的空窗问题。
- 能说清 Storage 与 Retain、Liveliness 与 LWT 的对应关系和差异。
- 能按「配置 -> 会话 -> 声明 -> 回调 -> 业务线程 -> 发布 -> 存活性/安全」阅读项目代码。

### 10.2、回到实际项目时优先补全的信息

本文是通用框架，Zenoh 的配置项与 API 在不同大版本间有明显演进，最终以项目所用版本的官方文档和实际行为为准。查代码或问同事时，优先拿到：Zenoh 版本与语言绑定、各节点的模式与端点配置、完整键空间清单、每个键的可靠性/拥塞/优先级设置、载荷格式与 Encoding 约定、Storage 与桥接插件配置、存活性检测方式、安全配置（TLS/ACL），以及是否与 ROS 2/DDS 互通及其映射规则。拿到这些信息后，本笔记第七章的表格就是最快的项目对照表。
