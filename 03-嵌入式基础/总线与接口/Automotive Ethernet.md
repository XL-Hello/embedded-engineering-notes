# Automotive Ethernet 汽车以太网基础知识总结

> 目标：这篇文档只作为 Automotive Ethernet（汽车以太网）入门、实际开发理解和项目面试复习使用，不展开完整的整车 E/E 架构、AUTOSAR 配置细节、功能安全认证和复杂 TSN 调度算法。重点记住：汽车以太网是什么、为什么使用单对双绞线、MAC 和 PHY 怎么连接、100BASE-T1/1000BASE-T1 是什么、Ethernet/IP/SOME-IP/DoIP 分别在哪一层、交换机怎么转发、TSN 解决什么问题，以及链路不通时应该怎么排查。
>
> 来源：文档结构仿照 CAN 基础知识总结的学习方式整理。技术内容重点参考 IEEE 802.3 Automotive Ethernet PHY 标准、IEEE 802.1 TSN 标准、OPEN Alliance 规范、AUTOSAR SOME/IP 规范和 ISO 13400 DoIP 规范。适合扫盲和面试复习，实际项目仍应以具体 PHY、Switch、SoC 数据手册和 OEM 网络规范为准。

## 第一章、基础认知与应用场景

本章先建立 Automotive Ethernet 的整体认识，再说明它在汽车项目中的作用，以及它与普通以太网的主要差异。

### 1.1、核心概念与快速理解

**Automotive Ethernet 本质上是把标准以太网技术适配到汽车环境中，用高带宽、可交换、可扩展的 Ethernet 网络连接车内 ECU、域控制器、摄像头、雷达、座舱和中央计算平台。**

它最典型的特点是：

- 仍然基于 IEEE 802.3 Ethernet。
- 车内常使用单对双绞线，而不是普通 PC 网口常见的多对双绞线。
- 常见 PHY 包括 `100BASE-T1`、`1000BASE-T1`、`2.5G/5G/10GBASE-T1`。
- 典型网络是点到点链路加 Ethernet Switch，而不是 CAN 那样所有节点直接挂在一条共享总线上。
- 二层仍然使用标准 Ethernet Frame 和 MAC Address。
- 上面可以运行 `IPv4/IPv6`、`TCP/UDP`。
- 汽车应用层常见 `SOME/IP`、`DoIP` 等协议。
- 对确定性时延、时间同步有要求时，可以引入 `TSN`。

常见用途：

| 用途 | 常见场景 |
| --- | --- |
| 智能驾驶 | 摄像头、雷达、域控制器、中央计算平台 |
| 智能座舱 | IVI、仪表、功放、显示控制、后排娱乐 |
| 车载网关 | CAN/LIN/FlexRay/Ethernet 网络之间的数据转发 |
| 诊断 | DoIP、刷写、车辆诊断 |
| 软件定义汽车 | 服务化通信、OTA、大数据传输 |
| 区域架构 | Zonal Controller 到 Central Computer 的骨干通信 |
| 音视频 | 摄像头视频、音频流、AVB/TSN |

简单记法：

- `MAC`：负责 Ethernet 帧收发。
- `PHY`：负责把数字数据变成线上电信号。
- `MDI`：PHY 面向双绞线的一侧。
- `100BASE-T1`：单对双绞线 100 Mbps Automotive Ethernet PHY。
- `1000BASE-T1`：单对双绞线 1 Gbps Automotive Ethernet PHY。
- `Switch`：根据 MAC 地址转发 Ethernet Frame。
- `SOME/IP`：汽车服务化通信协议。
- `DoIP`：基于 IP 的汽车诊断通信。
- `TSN`：让 Ethernet 更适合有确定性时延要求的业务。

### 1.2、在汽车项目中的作用

传统汽车网络中，CAN 很适合传输控制信号，例如：

- 开关状态。
- 车速。
- 温度。
- 电机控制命令。
- 故障状态。

但是当车内开始出现：

- 多路高清摄像头。
- 雷达点云。
- 高精地图。
- 座舱音视频。
- OTA 升级。
- 中央计算平台。
- 大量 ECU 之间的服务调用。

CAN 的带宽就明显不够了。

Automotive Ethernet 的价值可以简单理解为：

> 把车内通信从“低速信号总线”提升为“高带宽计算机网络”。

以摄像头把数据送到 ADAS 域控制器为例：

1. Camera ECU 采集图像。
2. 应用产生图像数据后，由协议栈按所选协议逐层封装；例如可采用 IEEE 1722 原生二层帧或 IP/UDP 封装、典型 RTP/UDP/IP，或者自定义协议。直接二层协议不经过 TCP/UDP 和 IP。
3. 封装后的数据交给本地 Ethernet Controller。协议栈、驱动与 MAC 硬件按具体实现共同完成帧头等内容，MAC 子层负责 Ethernet MAC Frame 的发送以及 FCS 等 MAC 功能。
4. PHY 把数字数据转换成 100BASE-T1 或 1000BASE-T1 物理信号。
5. 数据通过单对双绞线到达 Ethernet Switch。
6. Switch 根据目的 MAC 地址进行转发。
7. 域控制器 PHY 接收信号并恢复数据。
8. MAC 收到 Ethernet Frame。
9. 上层继续解析 VLAN、IP、UDP/TCP 或应用协议。
10. 最终交给图像、感知或业务模块处理。

下面是通用的 IP-based Automotive Ethernet 协议栈示意，不特指上述摄像头链路：

```text
Application
    │
SOME/IP / DoIP / RTP（通常基于 UDP） / 自定义协议
    │
TCP / UDP
    │
IPv4 / IPv6
    │
Ethernet MAC
    │
MII / RMII / RGMII / SGMII ...
    │
Ethernet PHY
    │ MDI
单对平衡双绞线链路段
（运行 100BASE-T1 / 1000BASE-T1）
    │ MDI
Switch 端口 PHY / MAC
    │
Switch Fabric
    │
Switch 端口 MAC / PHY
    │ MDI
单对平衡双绞线链路段
（运行 100BASE-T1 / 1000BASE-T1）
    │ MDI
目标 ECU PHY → MAC → 上层协议
```

如果使用自定义 EtherType 等直接二层协议，数据会从相应协议直接交给 Ethernet MAC，跳过 TCP/UDP 和 IP。

这里最重要的概念是：

> `100BASE-T1` 解决的是“数据怎么在线上传输”，SOME/IP、DoIP 解决的是“上层数据怎么组织和使用”，两者不是同一层的协议。

### 1.3、与普通以太网的差异

汽车以太网不是重新发明一套完全不同的 Ethernet。

它仍然保留大量标准 Ethernet 技术，例如：

- Ethernet Frame。
- MAC Address。
- VLAN。
- Ethernet Switch。
- IPv4/IPv6。
- TCP/UDP。
- PTP/时间同步。

真正变化最大的地方之一是物理层。

普通家用或办公网络常见：

- `100BASE-TX`
- `1000BASE-T`
- RJ45。
- CAT5e/CAT6 网线。
- 多对双绞线。

车载环境更关注：

- 线束重量。
- 连接器体积。
- 成本。
- EMC/EMI。
- 温度范围。
- 振动。
- 睡眠和唤醒。
- 诊断能力。
- 车规可靠性。

因此 Automotive Ethernet 常使用：

- 单对双绞线。
- 车规连接器。
- Automotive Ethernet PHY。
- 汽车专用 EMC、线束和一致性规范。

简单对比：

| 对比项 | 普通以太网 | Automotive Ethernet |
| --- | --- | --- |
| 主要环境 | 家庭、办公室、数据中心 | 汽车内部 |
| 常见物理层 | 100BASE-TX、1000BASE-T | 100BASE-T1、1000BASE-T1 |
| 铜线 | 多对双绞线常见 | 单对双绞线常见 |
| 连接器 | RJ45 常见 | 车规连接器 |
| 线束要求 | 一般网络布线 | 重量、空间、EMC 要求高 |
| 睡眠唤醒 | 一般不是核心需求 | 重要工程能力，具体支持依实现而定 |
| 诊断 | 普通网络诊断 | PHY、线束、ECU 诊断要求更强 |
| 实时性 | Best Effort 为主 | 可结合 TSN 提供确定性能力 |

Sleep/Wake 是汽车网络的重要工程能力，但并非所有 IEEE BASE-T1 PHY 都强制具备。具体支持和实现取决于 PHY、OPEN Alliance TC10 等相关规范以及 OEM 要求。

## 第二章、硬件组成、物理层与交换网络

本章沿着数据从控制器到线缆、再进入交换网络的路径，介绍 MAC、PHY、T1 物理层、Ethernet Frame 和 Switch。

### 2.1、MAC、PHY 和单对双绞线

#### 2.1.1、MAC

MAC 通常位于 MCU、MPU 或 SoC 内部。

它负责：

- 组织并发送 Ethernet MAC Frame。
- 接收并解析 Ethernet MAC Frame。
- 执行目的地址识别、地址过滤及相关 MAC 地址处理。
- 处理 CRC/FCS。

具体帧头字段由协议栈、驱动与 MAC 硬件如何分工取决于 Ethernet Controller 的实现。例如 Destination/Source MAC、EtherType 和 VLAN Tag 可能由软件提供，也可能由硬件插入或处理。

在很多 MCU、MPU 或 SoC 的 Ethernet Controller 中，MAC 旁边还会集成 DMA 和主机接口模块。DMA Descriptor、Buffer 管理以及与系统内存之间的数据搬运，通常属于这些控制器模块的职责，不是 IEEE 802.3 MAC 子层本身的固有功能。

可以把 MAC 理解为：

> MAC 负责 Ethernet MAC Frame 在数据链路层的组织、介质访问与收发。

#### 2.1.2、PHY

PHY 是 Physical Layer Transceiver。

它负责：

- 编码和解码。
- 发送模拟前端。
- 接收模拟前端。
- 时钟恢复。
- 信号检测。
- 链路建立。
- 将 MAC 的数字接口转换成线上的物理信号。

部分 Automotive Ethernet PHY 还会提供：

- 线缆诊断。
- SQI 等信号质量指标。
- 睡眠和唤醒（若 PHY 支持）。

这些附加能力及其配置方式应以具体 PHY 数据手册、OPEN Alliance 规范和 OEM 要求为准。

可以把 PHY 理解为：

> PHY 决定“这些 bit 怎么真正跑到线缆上”。

常见硬件结构：

```text
        SoC / MCU
┌──────────────────────┐
│                      │
│  Application         │
│       │              │
│  TCP/IP Stack        │
│       │              │
│  Ethernet MAC        │
│       │              │
└───────┼──────────────┘
        │
   RGMII / RMII
   SGMII / MII
        │
┌───────┼──────────────┐
│ Automotive Ethernet  │
│        PHY           │
└───────┼──────────────┘
        │ MDI
        │
    单对双绞线
        │
┌───────┼──────────────┐
│      对端 PHY        │
└──────────────────────┘
```

#### 2.1.3、MAC-PHY 数据与管理接口

常见数字接口包括：

| 接口 | 常见用途 |
| --- | --- |
| `MII` | 10/100M Ethernet |
| `RMII` | 简化版 10/100M MAC-PHY 接口 |
| `RGMII` | 常用于 1G Ethernet |
| `SGMII` | 串行 MAC-PHY 接口 |
| `XFI/USXGMII` | 更高速率场景 |

此外通常还有 PHY 管理接口：

```text
MDC
MDIO
```

用途主要是：

- 读取 PHY ID。
- 配置 Master/Slave。
- 启动 PHY。
- 读取 Link Status。
- 配置睡眠/唤醒（若 PHY 支持）。
- 读取诊断寄存器。
- 读取 SQI。
- 配置回环模式。

因此开发时要把两条路径区分开：

```text
数据路径：MAC <---- RGMII/SGMII ----> PHY
管理路径：MAC/MCU <---- MDIO/MDC ----> PHY Registers
```

不要看到 MDIO 就以为 Ethernet 数据都从 MDIO 上传。

### 2.2、使用单对双绞线的原因

传统 100BASE-TX、1000BASE-T 通常需要多对双绞线。

汽车里线束非常多。

如果每个高速节点都使用普通网络线：

- 线束会更重。
- 连接器更大。
- 成本更高。
- 布线更加困难。

Automotive Ethernet 的 T1 系列 PHY 使用单对平衡导线传输。

典型优势：

- 减少铜线。
- 减轻线束重量。
- 减少连接器体积。
- 更适合车内空间。
- 满足车载 EMC 设计需求。

以 `100BASE-T1` 为例，它支持：

- 单对平衡双绞线。
- 100 Mbps。
- 点到点。
- 全双工。

这里有一个很容易误解的地方：

> 全双工并不意味着一定需要两对线。

100BASE-T1 可以在同一对线上同时发送和接收。

PHY 内部通过混合电路、回波抵消和数字信号处理等方式，把：

```text
本端发送信号
+
对端发送信号
```

从同一对双绞线中分离出来。

所以：

```text
ECU A PHY  <==================>  ECU B PHY
                 1 Pair
            TX + RX 同时进行
```

这和 UART 的 TX/RX 两根独立数据线思路完全不同。

### 2.3、常见 Automotive Ethernet PHY

当前最需要掌握的几种是：

| PHY | 速率 | 典型拓扑 | 标准 |
| --- | ---: | --- | --- |
| `10BASE-T1S` | 10 Mbps | 半双工点到点为基本模式；全双工点到点、半双工多点为可选能力 | IEEE 802.3cg |
| `100BASE-T1` | 100 Mbps | 点到点 | IEEE 802.3bw |
| `1000BASE-T1` | 1 Gbps | 点到点 | IEEE 802.3bp |
| `2.5GBASE-T1` | 2.5 Gbps | 点到点 | IEEE 802.3ch |
| `5GBASE-T1` | 5 Gbps | 点到点 | IEEE 802.3ch |
| `10GBASE-T1` | 10 Gbps | 点到点 | IEEE 802.3ch |
| `25GBASE-T1` | 25 Gbps | 点到点 | IEEE 802.3cy |

#### 2.3.1、100BASE-T1

这是汽车以太网里非常经典的一种 PHY。

核心特点：

- 100 Mbps。
- 单对双绞线。
- 点到点。
- 全双工。
- 主要用于 ECU、摄像头、域控制器和交换机之间的连接。

典型结构：

```text
ECU A
 MAC
  │
 PHY
  │
  ├==========================┤
       Single Twisted Pair
  ├==========================┤
  │
 PHY
  │
Switch / ECU B
```

#### 2.3.2、1000BASE-T1

1000BASE-T1 可以简单理解成更高带宽的 Automotive Ethernet PHY：

- 1 Gbps。
- 单对双绞线。
- 点到点。
- 全双工，每个方向均可达到 1 Gbit/s。
- 面向更高数据量场景。

常见场景：

- 高分辨率摄像头。
- ADAS。
- 高性能域控制器。
- 中央计算平台。
- 高带宽骨干网络。

#### 2.3.3、Multi-Gigabit Ethernet

对于更高带宽需求，还有：

- 2.5GBASE-T1。
- 5GBASE-T1。
- 10GBASE-T1。
- 25GBASE-T1。

这类速率更多面向：

- 高性能计算平台。
- 多传感器融合。
- 高分辨率视频。
- 车内高速骨干。

学习入门时没必要先研究这些 PHY 的复杂编码细节。

优先理解：

```text
100BASE-T1
    ↓
1000BASE-T1
    ↓
Multi-Gigabit T1
```

本质上都是：

> 使用适合汽车环境的 Ethernet PHY，把标准 Ethernet 数据送到车内高速链路上。

#### 2.3.4、10BASE-T1S 的特殊性

10BASE-T1S 的目标不只是“更慢的 Ethernet”。

它的一个重要价值是让 Ethernet 可以进一步下沉到：

- 传感器。
- 执行器。
- 小型 ECU。
- 区域控制器边缘节点。

它支持 10 Mbps。半双工点到点是基本模式；全双工点到点和半双工多点是需要 PHY 明确支持的可选能力。

例如：

```text
              10BASE-T1S
Node A ─────┬───────────┬───────────┬──── Node D
            │           │           │
          Node B      Node C      Node E
```

这和典型 100BASE-T1 的：

```text
Node A <----------> Switch
Node B <----------> Switch
Node C <----------> Switch
```

明显不同。

在 10BASE-T1S 多点模式中，多个节点共享 10 Mbps 带宽。

从 IEEE 802.3 的 10BASE-T1S 能力定义看，`PLCA` 是可选功能，可用于降低传统共享 Ethernet 中随机碰撞带来的不确定性：

```text
Physical Layer Collision Avoidance
```

可以直白理解为：

> 给节点安排发送机会，尽量不要让大家同时抢总线。

从汽车工程落地看，OPEN Alliance 的 10BASE-T1S System Implementation Specification 以所有节点均启用 PLCA 的 `pure PLCA network` 为实现范围。因此，通用 IEEE 802.3 选型仍要分别确认 PHY 的 Multidrop 与 PLCA 能力；按该 OPEN Alliance 汽车实现规范设计多点网络时，则应让所有节点启用 PLCA。

注意：

- 不要把 10BASE-T1S 的共享总线特性套到 100BASE-T1 上。
- 100BASE-T1、1000BASE-T1 的典型链路是点到点。
- 10BASE-T1S 是 Automotive Ethernet 向低成本边缘节点扩展的重要方向。

### 2.4、Ethernet Frame 基本格式

Automotive Ethernet 在二层仍然使用 Ethernet Frame。

严格区分时，Preamble 和 SFD 位于 MAC Frame 之前；把它们与 MAC Frame 合在一起描述的是线上 Ethernet Packet。常见 Ethernet II MAC Frame 可以粗略理解成：

| 字段 | 长度 | 含义 |
| --- | ---: | --- |
| Destination MAC | 6 Byte | 目的 MAC 地址 |
| Source MAC | 6 Byte | 源 MAC 地址 |
| 802.1Q Tag | 可选，4 Byte | 位于 Source MAC 与 EtherType 之间，携带 VLAN 和优先级信息 |
| EtherType | 2 Byte | 上层协议类型 |
| MAC Client Data / Pad | 未标记帧通常为 46～1500 Byte | 上层数据；不足最小帧长时由 Pad 补齐 |
| FCS | 4 Byte | CRC32 校验 |

需要注意：

- 线上发送时，MAC Frame 前还有 7 Byte Preamble 和 1 Byte SFD。
- 常见 Ethernet MTU 是 1500 Byte。
- 这里的 MTU 通常指最大 MAC Client Data 长度；承载 IP 时，对应最大 IP 数据报长度，包含 IP Header，不是应用层可用数据长度。
- 单个 802.1Q VLAN Tag 会使常见最大 MAC Frame 长度由 1518 Byte 增加到 1522 Byte，但通常不改变 1500 Byte MTU。
- Ethernet 二层主要通过 MAC Address 进行转发。
- IP Address 属于三层。
- TCP/UDP Port 属于四层。

简单分层：

```text
Ethernet Frame
┌──────────────────────────────────────────┐
│ Destination MAC                         │
│ Source MAC                              │
│ 802.1Q Tag（可选）                       │
│ EtherType                               │
│                                          │
│   IP Packet                              │
│   ┌──────────────────────────────────┐   │
│   │ IP Header                        │   │
│   │                                  │   │
│   │   UDP/TCP                        │   │
│   │   ┌──────────────────────────┐   │   │
│   │   │ Application Payload     │   │   │
│   │   └──────────────────────────┘   │   │
│   └──────────────────────────────────┘   │
│                                          │
│ FCS                                      │
└──────────────────────────────────────────┘
```

不要混淆：

```text
MAC Address ≠ IP Address ≠ Port
```

三者分别解决不同层的问题。

### 2.5、交换网络与 Switch

CAN 是广播式共享总线。

典型 100BASE-T1 Automotive Ethernet 则通常使用点到点连接。

要把多个 100BASE-T1/1000BASE-T1 点到点端口接入同一个二层网络，通常需要 Ethernet Switch。10BASE-T1S 半双工多点共享网络是一个例外。

例如：

```text
                     ┌──────── Camera
                     │
                     │ 100BASE-T1
                ┌────┴─────┐
ADAS ECU ───────┤ Ethernet ├──────── Radar
                │  Switch  │
IVI ────────────┤          ├──────── Gateway
                └──────────┘
```

Switch 的主要作用：

- 根据目的 MAC 地址转发数据。
- 把多个点到点 PHY 链路组成一个 Ethernet 网络。
- 隔离不同端口上的无关流量。
- 支持 VLAN。
- 支持 QoS。
- 高级车载 Switch 可以支持 TSN、时间同步、MACsec、镜像等功能。

**Switch 的 MAC 地址学习与转发**

Ethernet Switch 会学习：

```text
Source MAC Address
```

然后形成类似：

```text
MAC Address         Port
AA:BB:CC:00:00:01   Port 1
AA:BB:CC:00:00:02   Port 2
AA:BB:CC:00:00:03   Port 5
```

之后收到目的 MAC 已知的帧时，就只从对应端口转发。

如果目的 MAC 未知，未知单播通常只会在所属 VLAN 内，向除入端口外、处于 Forwarding 状态且允许该 VLAN 的端口进行 Flooding；实际范围还会受到过滤、端口隔离和 ACL 等配置约束。

简单理解：

> CAN 依靠所有节点都听到报文后自己过滤；Ethernet Switch 会主动决定报文应该往哪个端口走。

## 第三章、协议栈与关键通信机制

本章从协议分层出发，依次说明 SOME/IP、DoIP、VLAN、QoS、TSN，以及点到点 PHY 链路中的角色配置。

### 3.1、Ethernet、IP、TCP/UDP 与应用协议的关系

这是 Automotive Ethernet 最容易混乱的部分。

可以按层理解：

```text
┌───────────────────────────┐
│ Application               │
│ SOME/IP / DoIP / HTTP ... │
├───────────────────────────┤
│ Transport                 │
│ TCP / UDP                 │
├───────────────────────────┤
│ Network                   │
│ IPv4 / IPv6               │
├───────────────────────────┤
│ Data Link                 │
│ Ethernet MAC / VLAN       │
├───────────────────────────┤
│ Physical                  │
│ 100BASE-T1 / 1000BASE-T1  │
└───────────────────────────┘
```

可以用一条链路记忆：

```text
SOME/IP
   ↓
UDP/TCP
   ↓
IP
   ↓
Ethernet Frame
   ↓
MAC
   ↓
PHY
   ↓
100BASE-T1
```

因此下面这些说法都是错误的：

```text
“100BASE-T1 是应用层协议”
“SOME/IP 是 Ethernet PHY”
“DoIP 是一种网线”
“TCP 和 Ethernet 是同一层”
```

### 3.2、SOME/IP 服务化通信

`SOME/IP` 全称：

```text
Scalable service-Oriented MiddlewarE over IP
```

它是 AUTOSAR 定义的汽车/嵌入式服务化通信协议之一。

SOME/IP 主要解决：

- ECU 之间的服务调用。
- Method。
- Event。
- Field。
- 序列化。
- 请求/响应。
- 事件通知。

例如某个 ECU 提供：

```text
VehicleSpeedService
```

里面可能有：

```text
Method:
    GetSpeed()

Event:
    SpeedChanged

Field:
    CurrentSpeed
```

其他 ECU 不需要知道：

```text
“车速一定在 CAN ID 0x123 的 Byte2~Byte3”
```

而是可以从“服务”的角度理解数据。

简单类比：

CAN 思维：

```text
我关心 ID = 0x123
```

SOME/IP 服务化思维：

```text
我关心 VehicleSpeedService
```

#### 3.2.1、SOME/IP 的 TCP/UDP 承载

不一定。

SOME/IP 可以根据场景运行在：

```text
UDP
或
TCP
```

因此不能简单背成：

```text
SOME/IP = TCP 协议
```

#### 3.2.2、SOME/IP-SD 服务发现

`SOME/IP-SD`：

```text
Service Discovery
```

主要解决：

- 谁提供某个 Service。
- Service 在哪里。
- 服务是否可用。
- Client 如何订阅 Event。

可以简单理解为：

> SOME/IP 负责真正的服务通信，SOME/IP-SD 负责发现服务和订阅关系。

SOME/IP-SD 报文本身使用 UDP，可以通过单播或组播发送。不要把普通 SOME/IP 支持 TCP/UDP 的结论直接套到 SOME/IP-SD 上。

### 3.3、DoIP 诊断通信

`DoIP`：

```text
Diagnostics over Internet Protocol
```

DoIP 对应 ISO 13400 系列标准，其中核心传输协议和网络层服务由 `ISO 13400-2:2025` 定义。

它主要解决：

> 把汽车诊断通信运行在 IP 网络之上。

传统诊断可能走：

```text
UDS
 ↓
ISO-TP
 ↓
CAN
```

典型 UDS over DoIP 诊断消息链路可以理解为：

```text
UDS
 ↓
DoIP
 ↓
TCP/IP
 ↓
Ethernet
```

车辆发现、车辆公告和部分状态查询则使用另一条路径：

```text
DoIP Discovery / Status
  ↓
UDP/IP
  ↓
Ethernet
```

Routing Activation 和后续诊断消息在建立的 TCP 连接上传输；UDP 主要用于发现、公告和部分状态类消息。

典型用途：

- 整车诊断。
- ECU 诊断。
- 软件刷写。
- 售后诊断设备连接。
- 工厂下线诊断。

DoIP 常会涉及：

- Vehicle Identification。
- Routing Activation。
- Diagnostic Message。
- TCP。
- UDP。
- IP。

重点：

> DoIP 不是替代 UDS 的诊断服务本身，它主要是把诊断数据放到 IP 网络上传输。

更严格地说，`ISO 13400-2:2025` 定义 DoIP 的传输协议和网络层服务，UDS over IP 的相关诊断框架由 ISO 14229-5:2022 定义。

### 3.4、VLAN、QoS 与 TSN

普通 Ethernet 的核心思想是：

```text
Best Effort
```

也就是尽力而为。

对于：

- 文件下载。
- 网页。
- 普通数据同步。

通常问题不大。

但是汽车里有些数据可能要求：

- 周期稳定。
- 延迟上限明确。
- 抖动小。
- 时间同步。
- 高优先级数据不能被大流量阻塞。

这时就会用到：

- VLAN。
- Priority。
- QoS。
- TSN。

#### 3.4.1、VLAN

802.1Q VLAN 可以给 Ethernet Frame 增加 VLAN Tag。

它可以用于：

- 网络隔离。
- 逻辑划分。
- QoS Priority。
- 限制广播域。

例如：

```text
VLAN 10：ADAS
VLAN 20：IVI
VLAN 30：Diagnostic
```

即使它们经过同一台 Switch，也可以进行逻辑隔离。

#### 3.4.2、QoS

QoS 用于根据优先级对流量进行不同处理。

例如：

```text
高优先级：
制动相关控制数据

中优先级：
摄像头控制信息

低优先级：
日志上传
```

Switch 内部通常存在多个 Queue。

如果所有数据都塞进一个 FIFO：

```text
4K 视频大包
4K 视频大包
4K 视频大包
关键控制帧
```

关键帧必须等待前面已经排队的大帧发送，因而产生较大的排队时延。

QoS 可以让高优先级流量进入更高优先级 Queue，从而减少排队等待；但它不能中断已经开始发送的低优先级帧。需要进一步降低这类非抢占式阻塞时，可以使用 `802.1Qbu / 802.3br` Frame Preemption。

#### 3.4.3、TSN

TSN：

```text
Time-Sensitive Networking
```

不是某一个单独协议，而是一组 IEEE 802.1 标准能力。

核心目标：

> 在标准 Ethernet 基础上增加时间同步、流量调度、资源预留、帧抢占等能力，使网络具备更可控的时延和确定性。

车载网络中常见相关概念：

- `IEEE 802.1AS-2025`：时间同步。
- `802.1Qbv`：Time-Aware Shaper。
- `802.1Qbu / 802.3br`：Frame Preemption。
- `802.1Qci`：Per-Stream Filtering and Policing。
- `802.1Qav`：Credit-Based Shaper。

不需要入门阶段把所有编号背下来。

优先理解：

```text
时间同步
    ↓
流量分类
    ↓
队列调度
    ↓
控制关键数据的最坏时延
```

#### 3.4.4、IEEE 802.1AS-2025 / gPTP 时间同步

很多 TSN 能力依赖各节点拥有统一时间基准。

现行的 `IEEE 802.1AS-2025` 提供网络时间同步能力，并取代 IEEE 802.1AS-2020。

常见概念：

- `gPTP`：IEEE 802.1AS 使用的精确时间同步机制。
- `Grandmaster`：同步域中选出的根时间源。
- `timeTransmitter / timeReceiver`：端口级的时间发送/接收角色；Bridge 的端口可以是 timeTransmitter，但该 Bridge 不一定是 Grandmaster。
- `Bridge / End Station`：中间桥设备和端系统。
- `Timestamp / Path Delay`：用于计算时间偏差和链路时延。

旧版 IEEE 802.1AS、IEEE 1588 或芯片资料可能仍使用 master/slave port 等术语；IEEE 802.1AS-2025 使用 timeTransmitter/timeReceiver 等术语，应结合资料版本理解。

例如：

```text
Camera
   │
   ├── 时间 10:00:00.123456
   │
Radar
   │
   ├── 时间 10:00:00.123457
   │
ADAS ECU
```

时间同步后，来自不同传感器的数据更容易进行时间对齐和融合。

### 3.5、PHY Master / Slave 链路角色

在 100BASE-T1、1000BASE-T1 等点到点 PHY 链路中，会涉及链路时钟角色配置。

不同芯片资料可能使用：

```text
Master / Slave
```

或者：

```text
Leader / Follower
```

实际开发时必须以 PHY 数据手册使用的术语为准。

核心理解：

- 对 100BASE-T1，一条链路必须一端为 Master、另一端为 Slave；两端同时为 Master 或同时为 Slave 都会导致链路无法建立。
- 100BASE-T1 的角色通常通过 Strap Pin 或寄存器配置，不通过标准 Auto-Negotiation 自动解决角色。
- 1000BASE-T1 的 Clause 98 Auto-Negotiation 是可选能力；多速率 BASE-T1 PHY 是否使用标准或厂商自定义的协商机制，也应分别查阅对应标准和芯片数据手册。
- 这个 Master/Slave 是 PHY 链路时序角色，不是“应用层谁控制谁”。

因此：

```text
100BASE-T1 Master
```

不代表：

```text
这个 ECU 是整车主控制器
```

两者没有直接关系。

## 第四章、常见故障与分层排查

本章先按 MAC、PHY、MDI、Switch 和网络配置归纳常见故障，再给出从物理层到应用层的逐层排查流程。

### 4.1、硬件与网络常见故障点

Automotive Ethernet 的问题通常可以分成：

```text
MAC 侧
PHY 侧
MDI/线束侧
Switch 侧
IP/协议栈侧
应用协议侧
```

#### 4.1.1、MAC-PHY 接口配置错误

例如：

- MAC 配成 RGMII，硬件实际接的是 RMII。
- RGMII RX/TX Delay 配置错误。
- Reference Clock 方向配反。
- Interface Clock 不正常。
- GPIO Pinmux 配错。
- MAC 工作速率配置错误。

典型现象：

```text
PHY Link Up
但是收不到 Ethernet Frame
```

#### 4.1.2、MDIO/MDC 不通

如果 PHY 寄存器读不到：

优先检查：

- PHY Address。
- MDIO Pinmux。
- MDC Frequency。
- Pull-up。
- Reset。
- PHY Power。
- Clause 22 / Clause 45 访问方式。
- PHY 是否仍处于 Sleep。

典型调试第一步：

```text
读取 PHY ID
```

如果 PHY ID 都读不到，先别急着研究 SOME/IP。

#### 4.1.3、PHY 没退出 Reset

检查：

```text
RESET_N
EN
STANDBY
WAKE
INH
```

不同 PHY 命名不同。

常见问题：

- Reset 释放时序不满足要求。
- 电源还未稳定就释放 Reset。
- Strap Pin 在 Reset 时采样错误。
- PHY 默认进入 Sleep。
- MCU 没有正确执行 Wake-up。

#### 4.1.4、Master/Slave 配置错误

点到点链路两端需要正确的 PHY 角色配置。

可能表现为：

```text
Link 一直 Down
```

因此应读取：

- PHY Control。
- Link Status。
- Master/Slave Status。
- Link Startup/Training 相关状态或厂商诊断寄存器（若 PHY 提供）。

不要只盯着 Linux 里的：

```text
eth0: link down
```

这行日志本身信息量很有限。

#### 4.1.5、线缆和 MDI 设计问题

检查：

- 双绞线型号。
- 线长。
- 连接器。
- 差分阻抗。
- PCB 差分走线。
- Common Mode Choke。
- AC Coupling。
- ESD 器件。
- Return Loss。
- Insertion Loss。
- Mode Conversion。
- EMC。

这里必须特别注意：

> Automotive Ethernet 的终端和 MDI 电路不能简单照搬 CAN 的“两端各 120Ω”。

100BASE-T1 的 MDI 匹配网络应按照：

- PHY Datasheet。
- Reference Design。
- OPEN Alliance Channel/Component Specification。

进行设计。

#### 4.1.6、PHY Signal Quality 差

很多 Automotive Ethernet PHY 提供：

```text
SQI
Signal Quality Indicator
```

如果：

```text
Link 能起来
但频繁丢包
CRC Error 多
```

可以检查：

- SQI。
- Cable Diagnostic。
- Receive Error。
- Link Drop Counter。
- SNR 相关状态。
- PHY Error Counter。

#### 4.1.7、Switch VLAN 配置错误

典型现象：

```text
PHY Link Up
本地能发包
但是数据到不了目标 ECU
```

可能原因：

- VLAN Membership 错。
- PVID 错。
- Tagged/Untagged 配置错。
- Port 被隔离。
- MAC Learning 异常。
- ACL 把流量丢了。
- STP 状态不对。
- Switch Port 没有正确 Forwarding。

#### 4.1.8、IP 配置错误

检查：

- IP Address。
- IPv4 Netmask / IPv6 Prefix Length。
- Gateway / IPv6 Default Router。
- IPv4 ARP。
- IPv6 NDP/ICMPv6。
- Route。
- DHCP / DHCPv6 / RA-SLAAC。
- Static IP。
- IPv4/IPv6。

如果双端抓到的帧完整，且 FCS/CRC、PHY 错误计数、SQI 和 Link Drop 都正常，可以优先转查 VLAN 与 IP 配置。如果存在 CRC、丢帧、低 SQI 或单向通信异常，即使能抓到部分 Ethernet Frame，也仍需继续检查 PHY、MDI 和线束。

调试一定要按层缩小范围。

### 4.2、网络不通的分层排查流程

推荐按：

```text
Power
 ↓
MDIO
 ↓
PHY
 ↓
Link
 ↓
MAC
 ↓
Ethernet Frame
 ↓
ARP/NDP/IP
 ↓
TCP/UDP
 ↓
SOME/IP / DoIP
 ↓
Application
```

逐层排查。

#### 4.2.1、第一步：确认 PHY 能否访问

最基础动作：

```text
read PHY ID
```

如果读不到：

检查：

- 电源。
- Reset。
- Clock。
- MDIO。
- MDC。
- PHY Address。
- Pinmux。

如果能读到 PHY ID，说明：

```text
CPU → MDIO → PHY
```

这条管理路径至少基本正常。

#### 4.2.2、第二步：检查 PHY Link Status

读取 PHY 提供的相关状态，例如：

```text
Link Status
Master/Slave
Link Startup/Training State（若 PHY 提供）
SQI
```

如果 Link Down：

优先排查：

- 对端是否上电。
- 线缆是否连接。
- PHY 模式是否一致。
- 100M/1G 类型是否匹配。
- Master/Slave。
- PHY 是否处于 Sleep。
- MDI 电路。
- 线束和连接器。

#### 4.2.3、第三步：Link Up 后检查 MAC

如果：

```text
PHY Link Up
但系统没有数据
```

检查：

- MAC Enable。
- RX/TX Enable。
- DMA。
- Descriptor。
- Cache Coherency。
- RGMII/RMII/SGMII 配置。
- Clock。
- Interrupt。
- RX Buffer。
- PHY Speed/Duplex 是否同步到 MAC。

嵌入式平台里常见问题：

```text
PHY 链路已经以 1 Gbit/s 建立
MAC 仍然按照 100 Mbps 配置
```

或者：

```text
RGMII 时序 Delay 配错
```

导致 CRC Error 或完全收不到帧。

#### 4.2.4、第四步：抓取 Ethernet Frame

常用工具：

- Wireshark。
- tcpdump。
- Switch Port Mirror。
- TAP。
- Automotive Ethernet Analyzer。
- 示波器。
- Vector CANoe / Ethernet 工具。
- 专业 PHY Compliance Test 工具。

先确认：

```text
有没有帧
```

再确认：

```text
帧是不是对的
```

不要一上来就分析业务代码。

#### 4.2.5、第五步：检查 ARP / NDP / IP

例如 ECU A：

```text
192.168.1.10
```

ECU B：

```text
192.168.1.20
```

先检查：

- IPv4：ARP、Ping、Route。
- IPv6：NDP/ICMPv6、Ping、Route。

如果同一子网内的邻居地址无法解析：

优先看：

- VLAN。
- IP。
- IPv4 Netmask / IPv6 Prefix Length。
- IPv6 RA、默认路由和地址配置。
- Switch。
- MAC Filter。

#### 4.2.6、第六步：检查 UDP/TCP

如果 Ping 正常：

通常说明本次源与目的之间、当前地址族和报文尺寸下的往返路径基本正常：

```text
PHY
MAC
Ethernet
IP
ICMP / ICMPv6
```

在同一 IPv4 子网且使用动态地址解析时，也通常说明 ARP 正常；IPv6 则对应 NDP。Ping 成功不代表链路完全无误，也不代表 TCP、UDP 或应用协议配置正确。

继续检查：

- TCP Connect。
- UDP Port。
- Socket Bind。
- Firewall。
- Port。
- Multicast。
- Buffer。
- MTU。

#### 4.2.7、第七步：检查 SOME/IP / DoIP

到这里再看：

- Service ID。
- Method ID。
- Event ID。
- Client ID。
- Session ID。
- 普通 SOME/IP 的 TCP/UDP Binding、端口和连接状态。
- SOME/IP-SD 的 UDP 端口、单播/组播、TTL 和订阅状态。
- DoIP Routing Activation。
- Diagnostic Address。
- UDS Service。

这种分层排查思路比：

```text
“收不到数据，直接怀疑 SOME/IP”
```

有效得多。

## 第五章、总线对比与驱动开发

本章先通过 CAN 对比明确 Automotive Ethernet 的适用边界，再落到 MCU/SoC Ethernet Driver 的实现重点。

### 5.1、Automotive Ethernet 与 CAN 对比

这是面试非常容易问的问题。

| 对比项 | CAN | Automotive Ethernet |
| --- | --- | --- |
| 网络方式 | 多主共享总线 | 点到点 + Switch 为主 |
| 典型带宽 | kbps ~ Mbps | 10 Mbps ~ 多 Gbps |
| 标识方式 | CAN ID | MAC/IP/Port/应用协议 |
| 介质访问/拥塞处理 | 共享总线通过 CAN ID 逐位仲裁 | 点到点全双工链路通常无介质争用；出口拥塞由队列、QoS 和 TSN 调度处理 |
| 数据长度 | Classic CAN Data Field 最大 8 Byte | 常见 Ethernet 二层 MAC Client Data 最大 1500 Byte |
| 物理层 | CAN_H/CAN_L | T1 单对双绞线常见 |
| 实时性 | 固定优先级、非破坏性位仲裁，在受控负载下可分析最坏响应时间 | 普通交换式 Ethernet 为 Best Effort，可通过 QoS/TSN 增强确定性 |
| 应用 | 控制信号 | 高带宽数据、服务化通信、诊断、音视频 |
| 网络扩展 | 总线增加节点 | Switch 扩展端口和网络 |
| 上层协议 | CAN Signal、J1939、UDS 等 | IP、TCP/UDP、SOME/IP、DoIP 等 |

直白理解：

> CAN 更像一条高可靠低速控制总线；Automotive Ethernet 更像车内的高速计算机网络。

两者不是简单的谁取代谁。

实际汽车中长期可能仍然共存：

```text
LIN
CAN / CAN FD
10BASE-T1S
100BASE-T1
1000BASE-T1
Multi-Gig Ethernet
```

根据成本、实时性、带宽和节点类型选择。

### 5.2、Ethernet 驱动开发要点

如果你做的是 MCU/SoC Ethernet Driver，通常需要关注下面几部分。

#### 5.2.1、Ethernet Controller / MAC 初始化

包括：

- MAC Clock。
- Pinmux。
- Interface Mode。
- MAC Address。
- RX/TX Enable。
- DMA。
- Descriptor Ring。
- Interrupt。
- Checksum Offload。
- MTU。

#### 5.2.2、PHY 初始化与运行时管理

初始化通常包括：

- Reset。
- PHY Address。
- MDIO。
- PHY ID。
- Master/Slave。
- Speed。

运行时管理以及部分车载 PHY 的可选能力还可能包括：

- 按芯片支持情况配置 Sleep/Wake。
- Link Status。
- Interrupt。
- 按芯片支持情况读取 SQI。
- 按芯片支持情况执行 Cable Diagnostic。

#### 5.2.3、Link State Machine

通常不能只初始化一次。

应处理：

```text
Link Down
   ↓
检测
   ↓
重新训练
   ↓
Link Up
   ↓
更新 MAC Speed/Duplex
   ↓
通知协议栈
```

Linux 中经常由：

```text
PHY framework / phylib / phylink
```

处理。

RTOS 或裸机项目则可能需要自己维护 Link State。

#### 5.2.4、DMA 和 Cache

高带宽 Ethernet 很容易遇到：

- DMA Descriptor 没同步。
- Cache 没 Clean。
- Cache 没 Invalidate。
- Buffer Alignment 错。
- RX Buffer 被提前复用。
- Descriptor Ownership 错。

典型链路：

```text
Application
   ↓
pbuf / skb / network buffer
   ↓
DMA Descriptor
   ↓
DMA
   ↓
MAC
   ↓
PHY
```

当出现：

```text
偶发丢包
数据内容异常
CPU 看见旧数据
```

不要只怀疑网络协议，也要考虑 DMA 与 Cache 一致性。

#### 5.2.5、Zero-Copy

高吞吐量场景下，为减少：

```text
memcpy
```

可能使用：

```text
Zero-Copy
```

但设计会更复杂：

- Buffer 生命周期。
- DMA Ownership。
- Cache。
- Ref Count。
- RX Buffer Recycle。

低速 demo 能跑，不代表高负载网络就一定稳定。因此，Zero-Copy 必须在高吞吐、长时间和异常路径下重点验证 Buffer 生命周期、引用计数以及 DMA/Cache 一致性。

## 第六章、面试复习与速查

本章集中整理面试问答、常见误区和最简记忆要点，便于完成系统学习后快速复盘。

### 6.1、面试常见问法和直白回答

**1. Automotive Ethernet 是什么**

> Automotive Ethernet 是把 IEEE 802.3 Ethernet 技术应用到汽车内部网络的一套技术体系。它仍然使用 Ethernet Frame、MAC、Switch、IP 等标准网络机制，但物理层通常采用适合车载环境的单对双绞线 PHY，例如 100BASE-T1 和 1000BASE-T1，用于满足车内高带宽、低线束重量和可扩展网络需求。

**2. 100BASE-T1 是什么**

> 100BASE-T1 是 IEEE 802.3bw 定义的 Automotive Ethernet PHY，支持在单对平衡双绞线上进行 100 Mbps 点到点全双工通信。它主要解决车内 Ethernet 的物理层传输问题，不是应用层协议。

**3. 为什么 Automotive Ethernet 只用一对双绞线也能全双工**

> 因为 100BASE-T1 PHY 可以让两个方向的信号同时存在于同一对线上，并通过模拟前端、回波抵消和数字信号处理把本端发送信号与对端接收信号分离，所以一对线也可以实现全双工。

**4. MAC 和 PHY 有什么区别**

> MAC 负责 Ethernet Frame 的组织和收发，例如 MAC 地址、帧定界和 FCS；Ethernet Controller 中常与 MAC 集成的 DMA 模块负责描述符管理和内存数据搬运。PHY 负责真正的物理信号发送和接收，例如编码、模拟前端、时钟恢复和链路训练。MAC 和 PHY 之间通常通过 RMII、RGMII、SGMII 等接口连接，通过 MDIO/MDC 配置 PHY。

**5. MDIO 是干什么的**

> MDIO/MDC 是 PHY 的管理接口，用来读写 PHY 寄存器，例如读取 PHY ID、Link Status、配置 Master/Slave、读取 SQI 和诊断信息。真正的 Ethernet 数据通常走 MII/RMII/RGMII/SGMII 等数据接口，而不是 MDIO。

**6. Automotive Ethernet 为什么需要 Switch**

> 100BASE-T1 和 1000BASE-T1 主要是点到点链路，一个 PHY 端口通常只连接一个对端。要把多个这类点到点端口接入同一个二层网络，通常需要 Ethernet Switch 根据 MAC 地址、VLAN 和转发表转发数据；10BASE-T1S 半双工多点共享网络则不依赖这种交换式拓扑。

**7. SOME/IP 是什么**

> SOME/IP 是 AUTOSAR 定义的面向服务汽车通信协议，支持 Method、Event、Field、RPC 和序列化等能力，通常运行在 TCP 或 UDP/IP 之上。它属于上层通信协议，不是 Ethernet PHY。

**8. DoIP 是什么**

> DoIP 是 ISO 13400 系列定义的基于 IP 的汽车诊断通信，其中 ISO 13400-2:2025 规定核心传输协议和网络层服务。它常与 UDS 配合使用，可以用于 ECU 诊断和刷写。

**9. TSN 是什么**

> TSN 是一组 IEEE 802.1 时间敏感网络标准，用于在 Ethernet 上增加时间同步、队列调度、流量整形、帧抢占等能力，从而让关键业务获得更可控的时延和确定性。它不是一个单独协议。

**10. Automotive Ethernet Link Up 但 Ping 不通怎么查**

> 先确认 PHY Link Status、SQI 和 MAC 收发是否正常，再抓 Ethernet Frame：IPv4 看 ARP Request/Reply，IPv6 看 Neighbor Solicitation/Advertisement。如果邻居请求没有响应，重点查 VLAN、IP、前缀长度或 Netmask、Switch 转发和对端网络配置；如果连 Frame 都没有，再回到 MAC、DMA、RGMII/SGMII 和 PHY 配置排查。

**11. Link 一直 Down 怎么查**

> 先确认 PHY 能通过 MDIO 正常读取，然后检查对端上电、PHY 型号和速率、Master/Slave、Reset、Sleep/Wake、MDI 电路、线缆、连接器，以及 Link Startup/Training 相关状态或厂商诊断寄存器（若 PHY 提供）。不要还没建立物理链路就开始研究 TCP。

**12. Automotive Ethernet 和 CAN 最大区别是什么**

> CAN 是共享总线，依靠 CAN ID 进行仲裁和报文识别，适合低带宽控制通信；Automotive Ethernet 通常是点到点 PHY 加 Switch 的网络结构，带宽高很多，可以运行 IP、TCP/UDP、SOME/IP 和 DoIP，更适合高带宽数据和服务化通信。

### 6.2、高频易错点

| 错误说法 | 更准确的说法 |
| --- | --- |
| Automotive Ethernet 是一个应用层协议 | 它是一套车载 Ethernet 技术体系 |
| 100BASE-T1 就是 SOME/IP | 100BASE-T1 是 PHY，SOME/IP 是上层协议 |
| DoIP 就是 UDS | DoIP 主要提供 IP 诊断传输，UDS 定义诊断服务 |
| Ethernet 靠 IP 地址在 Switch 中转发 | 二层 Switch 主要根据 MAC 地址转发 |
| MAC 和 PHY 是一个东西 | MAC 处理帧，PHY 处理物理信号 |
| MDIO 用来传 Ethernet 数据 | MDIO 主要用于 PHY 管理 |
| 100BASE-T1 是共享总线 | 典型 100BASE-T1 是点到点全双工 |
| 100BASE-T1 一对线只能半双工 | 100BASE-T1 可在单对线上全双工 |
| 10BASE-T1S 和 100BASE-T1 拓扑完全一样 | IEEE 802.3 的 10BASE-T1S 可选支持半双工多点与 PLCA；OPEN Alliance 汽车多点实现规范面向所有节点启用 PLCA 的网络 |
| Link Up 就说明网络一定正常 | Link Up 只说明 PHY 物理链路建立 |
| Ping 通就说明 SOME/IP 一定正常 | Ping 主要验证到 IP 层，应用协议仍可能配置错误 |
| 汽车以太网也应该两端各接 120Ω | 不能照搬 CAN，MDI 匹配按 PHY/OPEN Alliance 规范设计 |
| Ethernet 天生就是确定性实时总线 | 普通 Ethernet 是 Best Effort，可通过 TSN 增强确定性 |
| TSN 是一个协议 | TSN 是一组 IEEE 802.1 标准能力 |
| Master PHY 就是主 ECU | PHY Master/Slave 主要是链路时钟角色 |
| 1000BASE-T1 就是普通 1000BASE-T | 两者都是 Ethernet，但物理层和线缆体系不同 |

### 6.3、最简记忆版

只想快速记住，可以背下面几句：

- Automotive Ethernet 本质上仍然是 IEEE Ethernet，只是针对汽车环境做了 PHY、线束、EMC、唤醒和诊断等适配。
- 车内常见 `100BASE-T1`、`1000BASE-T1`，使用单对双绞线。
- 100BASE-T1 是 100 Mbps、点到点、全双工 Automotive Ethernet PHY。
- 1000BASE-T1 是 1 Gbps、点到点、全双工 Automotive Ethernet PHY，每个方向均可达到 1 Gbit/s。
- 10BASE-T1S 是 10 Mbps；IEEE 802.3 中半双工点到点是基本模式，全双工点到点、半双工多点和 PLCA 是可选能力；OPEN Alliance 汽车多点实现规范面向所有节点启用 PLCA 的网络。
- MAC 负责 Ethernet Frame，PHY 负责把 bit 真正送到线上。
- MAC 和 PHY 常通过 RMII/RGMII/SGMII 等接口传数据，通过 MDIO/MDC 管理 PHY。
- Automotive Ethernet 二层仍然使用 MAC Address 和 Ethernet Frame。
- IP 在 Ethernet 上面，TCP/UDP 在 IP 上面。
- SOME/IP 是服务化通信协议，可以运行在 TCP 或 UDP 上。
- DoIP 是基于 IP 的汽车诊断通信。
- 典型 100BASE-T1/1000BASE-T1 网络通过 Ethernet Switch 把多个点到点端口接入同一二层网络；10BASE-T1S 多点模式是例外。
- 普通 Ethernet 是 Best Effort，需要 TSN 时可以增加时间同步和确定性调度能力。
- PHY Link Up 只说明物理链路建立，不代表 IP、TCP、SOME/IP 一定正常。
- 排查顺序优先按 `Power → MDIO → PHY → Link → MAC → Ethernet → ARP/NDP/IP → TCP/UDP → SOME/IP/DoIP → Application` 分层定位。

## 第七章、参考标准和规范

为避免把网上二手资料当圣旨，建议需要继续深入时优先看这些标准和官方规范：

- IEEE 802.3bw：100BASE-T1。
- IEEE 802.3bp：1000BASE-T1。
- IEEE 802.3cg：10BASE-T1S / 10BASE-T1L。
- IEEE 802.3ch：2.5G/5G/10GBASE-T1 Automotive Ethernet。
- IEEE 802.3cy：25GBASE-T1 Automotive Ethernet。
- IEEE 802.1Q：Bridge、VLAN 和相关 QoS/TSN 机制。
- IEEE 802.1AS-2025：Timing and Synchronization for Time-Sensitive Applications。
- IEEE 802.1DG-2025：Time-Sensitive Networking Profile for Automotive In-Vehicle Ethernet Communications。
- IEEE 1722-2025：Transport Protocol for Time-Sensitive Applications in Bridged Local Area Networks。
- OPEN Alliance：Automotive Ethernet PHY、Switch、Channel、ECU Test、Sleep/Wake、EMC 等规范。
- AUTOSAR SOME/IP Protocol Specification。
- AUTOSAR SOME/IP Service Discovery Specification。
- ISO 13400 系列：Diagnostics over Internet Protocol（DoIP）；核心传输协议和网络层服务见 ISO 13400-2:2025。
- ISO 14229-5:2022：Unified Diagnostic Services on Internet Protocol Implementation（UDSonIP）。
