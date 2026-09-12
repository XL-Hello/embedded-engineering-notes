# BLE：智能设备通信扫盲、代码阅读与面试准备

> 目标：理解 BLE 的角色、广播、连接、GATT 数据模型与可靠性边界；能在智能设备项目中快速定位广播、配对、服务、收发、断连与低功耗代码；能清楚回答常见面试问题。
>
> 核心结论：**BLE（Bluetooth Low Energy，低功耗蓝牙）是一套面向低功耗短距离通信的蓝牙协议体系。设备通常先通过广播被发现，再建立点对点连接；连接后，客户端按 GATT 的 Service / Characteristic 读取、写入或订阅数据。**

## 1. 先用一张图理解 BLE

```text
手机 App（Central / GATT Client）                  传感器/设备（Peripheral / GATT Server）
          |                                                    |
          | 扫描 Scan：接收 Advertising 广播                    |
          | <--------- 广播：名称、MAC、UUID、RSSI、厂商数据 -----|
          |                                                    |
          | -------- 建立连接 Connect ------------------------> |
          | <------- 连接参数：interval / latency / timeout ---|
          |                                                    |
          | -------- 服务发现 Service Discovery --------------> |
          | <------- Service / Characteristic / Descriptor ----|
          |                                                    |
          | -------- Write：下发命令 -------------------------> |
          | <------- Notify / Indicate：状态或数据 ------------|
```

BLE 不是“串口无线替代品”那么简单。它规定了发现、连接、安全、低功耗调度和数据组织方式；应用层常把一个 Characteristic 当作收发通道，但仍要约定命令格式、分包、版本、超时和幂等。

## 2. 用 Zigbee 快速迁移到 BLE

如果已经做过 Zigbee，BLE 不必从零理解。两者都在解决“发现设备、建立通信关系、描述设备能力、上报状态、下发控制”的问题；但 **Zigbee 偏多设备组网，BLE 的经典模式偏低功耗点对点连接**。因此应迁移数据模型和业务思路，不能把网络层机制直接照搬。

### 2.1 先看网络模型：组网与连接不是一回事

```text
Zigbee：多设备组网                         BLE：以手机连接周边设备为主

              Coordinator                            手机 / 平板
                   |                                  Central
        -----------------------                           |
        |           |         |                  -----------------
      灯节点      空调节点    窗帘节点               手环   鼠标   电容笔
      Router/End Device                            Peripheral

      可有路由、Mesh、长期在线                    一般由 Central 扫描、连接、收发
```

| 对比项 | Zigbee | BLE |
| --- | --- | --- |
| 核心侧重 | 多设备低功耗组网 | 近距离低功耗发现与连接通信 |
| 常见中心角色 | Coordinator | Central（手机/平板常见） |
| 终端设备 | Router / End Device | Peripheral |
| 网络形态 | 可形成星型、树型、Mesh | 经典场景为点对点；也可一对多、多角色，但不是 Zigbee Mesh 的直接替代 |
| 路由转发 | 协议可支持多跳路由 | 普通 BLE 连接不经其他设备转发；BLE Mesh 是独立的 Mesh 方案 |
| 典型场景 | 灯、传感器、网关、全屋设备 | 穿戴、键鼠、电容笔、配网、近距离控制 |

> 不要把 `Coordinator = Central`、`Node = Peripheral` 当成严格等号：它们只是便于入门的角色类比。尤其 BLE Central/Peripheral 描述的是一次连接中的角色；GATT Client/Server 则描述数据访问角色，两组角色相互独立。

### 2.2 数据模型对照：Endpoint/Cluster/Attribute 与 GATT

```text
Zigbee                                      BLE（GATT）
设备                                        设备
 └─ Endpoint                                 └─ Service
     └─ Cluster                                  └─ Characteristic（一个或多个）
         └─ Attribute                                └─ Value / Descriptor
```

| Zigbee 概念 | BLE 概念 | 可怎样理解 | 不能忽略的差异 |
| --- | --- | --- | --- |
| Endpoint | Service | 一个功能域的入口/集合 | Endpoint 是应用端点；Service 是一组 GATT Attribute |
| Cluster | 一组 Characteristic | 一组相关业务能力 | BLE 没有和 Cluster 完全一一对应的强制层级 |
| Attribute | Characteristic Value | 可读写的具体业务状态 | Characteristic 还带 Properties、权限、Descriptor 等元数据 |
| 属性上报 Report | Notify / Indicate | 设备主动推送状态变化 | Notify 不逐包确认；Indicate 有 ATT 确认 |
| 写属性 | Write Characteristic | 控制端下发命令/配置 | Write Response 只代表 GATT 接收，不代表业务已执行 |

例如，Zigbee 温控设备可有 `Endpoint -> 温控 Cluster -> 当前温度/目标温度`；BLE 可设计为 `Environment Service -> Current Temperature Characteristic / Target Temperature Characteristic`。二者都在向上层表达“设备有什么能力、当前值是多少、是否允许控制”。

### 2.3 把熟悉的业务流程映射过去

| Zigbee 中的经历 | BLE 中对应流程 | 重点关注 |
| --- | --- | --- |
| 扫描网络/发现设备 | Scan 接收 Advertising | 名称、Service UUID、厂商数据、RSSI、隐私地址 |
| 加入网络 | Connect 建立连接 | 连接事件、参数、配对/绑定、断线重连 |
| 枚举 Endpoint/Cluster | Service Discovery | Service、Characteristic、Descriptor、CCCD |
| 读取 Attribute | Read Characteristic | 权限、缓存、数据格式 |
| 写 Attribute 控制 | Write Characteristic | 帧校验、业务 ack、幂等、权限 |
| Attribute Report | Notify / Indicate | 订阅 CCCD、背压、序号、断线后重订阅 |

可以把 BLE 的完整心智路径记成：

```text
广播被发现 -> 建立连接 -> 发现 Service/Characteristic -> 订阅通知或下发 Write
       -> 设备处理业务 -> Notify/Indicate 返回状态 -> 断开后清理并重新广播
```

### 2.4 以电容笔为例：压力上报就是“属性上报”的迁移

```text
压感模块 / IMU / 按键
          |
        MCU 采样、滤波、算法
          |
  Stylus Service 的 Pressure Characteristic
          |
       Notify（压力、倾角、按键状态）
          |
       平板 App / 系统（Central / GATT Client）
```

这与 Zigbee 的“传感器值变化 -> Attribute Report -> 网关”在业务思想上相近；区别在于 BLE 通常需先建立连接，Client 写 CCCD 订阅后，Peripheral 才可向该连接发送 Notify。平板要修改笔的配置时，则是对对应 Characteristic 执行 Write。

### 2.5 面试时的简洁回答

> 我之前做过 Zigbee 设备接入，所以对发现设备、描述设备能力、状态上报和控制下发的思路比较熟悉。迁移到 BLE 时，我会把 Zigbee 的 Endpoint/Cluster/Attribute 对照为 BLE 的 Service/Characteristic/Value；属性上报对应 Notify 或 Indicate，写属性控制对应 Characteristic Write。两者的关键区别是 Zigbee 更偏多设备 Mesh 组网，而 BLE 更关注广播、连接管理和 GATT 数据访问，因此我会重点掌握 GAP、GATT、订阅、连接参数以及断连恢复。

## 3. 为什么智能设备常用 BLE

| 需求 | BLE 的对应能力 | 典型例子 |
| --- | --- | --- |
| 手机近距离配网/控制 | 手机原生支持扫描、连接和 GATT | App 配置 Wi-Fi、调试设备 |
| 电池设备长期工作 | 广播间隔、连接间隔、从机延迟可控 | 门锁、温湿度计、遥控器 |
| 低频小数据交互 | 小包传输、按需连接 | 读取状态、下发设置、同步时间 |
| 周边设备发现 | Advertising 无连接广播 | 手机列表显示附近设备 |
| 设备身份和加密 | 配对、绑定、LE Secure Connections | 受限配置、私有控制命令 |

BLE 不适合直接承担高码率、连续大数据流；吞吐会受 PHY、连接参数、MTU、通知节奏、手机系统调度和射频环境共同限制。传大文件时通常要评估分包、断点续传和校验，或改用 Wi-Fi/USB。

## 3. 四个角色与关键名词

| 名词 | 含义 | 看代码时常见名字 |
| --- | --- | --- |
| GAP | 负责可发现、可连接、角色、地址和连接管理 | `gap_event`、`advertising` |
| GATT | 定义连接后如何组织和访问数据 | `gatt_server`、`gattc` |
| Central | 主动扫描并发起连接的一方，常为手机 | `central`、`scanner` |
| Peripheral | 广播并接受连接的一方，常为设备 | `peripheral`、`adv` |
| GATT Server | 保存 Attribute 数据并响应访问的一方 | `service`、`characteristic` |
| GATT Client | 发起发现、读写、订阅的一方 | `discover`、`subscribe` |
| Service | 一组相关能力的集合，由 UUID 标识 | Battery Service、私有 Service |
| Characteristic | 可读/写/通知的一个业务数据点 | `rx_char`、`tx_char` |
| Descriptor | Characteristic 的附加配置/说明 | CCCD |
| UUID | Service/Characteristic 的唯一标识 | 16-bit 或 128-bit UUID |

角色不要强行一一绑定：设备可以同时做 Peripheral 和 Central，也可同时是 GATT Server 与 GATT Client。实际能力由芯片、协议栈和产品设计决定。

## 4. 广播：未连接时怎样被发现

```text
Peripheral                                      手机
  |  每隔 advertising interval 发一次广播包       |
  |  AdvA（地址）+ AdvData（名称/UUID/厂商数据）  |
  +---------------------------------------------> |
                                                    | 扫描、按名称/UUID/RSSI 筛选
  | <---------------------------------------------+ | Scan Request（可扫描广播时）
  +----------------------------------------------> | Scan Response（补充数据）
```

| 广播类型/概念 | 用途 | 注意点 |
| --- | --- | --- |
| 可连接广播 | 允许 Central 发起连接 | 配网、控制设备常用 |
| 不可连接广播 | 只供附近设备接收 | Beacon、状态播报 |
| 可扫描广播 | 可通过 Scan Response 补充数据 | 不能假设所有扫描端都会拿到 |
| 广播间隔 | 两次广播的时间间隔 | 越短发现越快，耗电越大 |
| RSSI | 接收信号强度估计 | 波动大，只能作粗略距离/筛选依据 |

广播包空间有限，不应塞完整 JSON、密钥或过长设备信息。常见做法是放产品标识、协议版本、短设备 ID、状态位和厂商数据；需要完整信息时，连上后通过 GATT 读取。

### 4.1 地址与隐私

BLE 可能使用公开地址、随机静态地址或可解析私有地址（RPA）。因此不要把扫描到的 MAC 永远当成稳定设备身份；若启用隐私地址，地址会轮换。产品应使用受控的设备序列号、绑定信息或服务内身份特征来识别设备。

## 5. 连接到收发：完整链路

```text
Central / Client                              Peripheral / Server
       | -------- 扫描并选择设备 ----------------> |
       | -------- CONNECT -----------------------> |
       | <------- 连接建立 ----------------------- |
       | -------- MTU Exchange（可选） ----------> |
       | -------- Service Discovery -------------> |
       | <------- Service / Char / Descriptor ----|
       | -------- 写 CCCD，开启 Notify/Indicate -->|
       | -------- Write Command -----------------> |
       | <------- Write Response（若带响应） ------|
       | <------- Notify / Indicate --------------|
       | -------- Handle Value Confirmation -----> |  （仅 Indicate）
       | -------- Disconnect（或超时断开） -------> |
```

代码中通常由 BLE 协议栈完成底层 LL/L2CAP/ATT 报文。业务侧重点是：何时开始广播、连接事件、何时发现服务、特征权限、写入校验、通知订阅、连接参数更新和断线恢复。

## 6. GATT：把“数据通道”拆成可访问的属性

```text
自定义设备服务（128-bit UUID）
├─ Device Info Characteristic：READ
├─ Command RX Characteristic：WRITE / WRITE_NO_RSP
├─ State TX Characteristic：NOTIFY / INDICATE
└─ Config Characteristic：READ / WRITE（需加密）
```

| 操作 | 谁主动 | 适用场景 | 注意点 |
| --- | --- | --- | --- |
| Read | Client | 读取版本、当前配置 | 是一次请求/响应，不适合连续状态流 |
| Write with Response | Client | 关键命令、配置 | 有 ATT 层响应；不等于业务已执行成功 |
| Write without Response | Client | 高频、可容忍应用自控流的命令 | 可能被队列/链路限制；需自己做节流与应答 |
| Notify | Server | 连续状态、传感器数据 | 不要求对端逐包确认，可能丢/拥塞 |
| Indicate | Server | 重要状态、关键结果 | 等待确认，吞吐低于 Notify |

**CCCD（Client Characteristic Configuration Descriptor）** 是 Client 为某个 Characteristic 开启 Notify 或 Indicate 的配置。连接重建后不要假设订阅还在；通常应重新订阅，Server 也应在连接事件中清理对应连接的订阅状态。

## 7. MTU、分包与吞吐：不要把特征值长度想成无限

ATT 的默认 MTU 常为 23 字节，其中单个 ATT 载荷通常只有 20 字节可用；双方协商到更大 MTU 后，单包可用载荷才增加。实际值仍受控制器 Data Length、PHY、协议栈缓冲区、手机实现和连接参数限制。

| 影响项 | 作用 | 常见误区 |
| --- | --- | --- |
| MTU | 单个 ATT PDU 的最大长度 | 只改一端、未协商就假设可发大包 |
| Data Length Extension | 链路层单包长度能力 | 不等于应用可无限增大 Characteristic |
| PHY（1M/2M/Coded） | 空口速率/距离取舍 | 2M 不一定端到端吞吐翻倍 |
| Connection Interval | 连接事件间隔 | 越短越快但更耗电、占空口 |
| Slave Latency | Peripheral 可跳过的连接事件数 | 省电但会增加响应延迟 |

业务消息超过单包时，要定义应用层帧：`版本 + 类型 + 序号 + 总长/分片序号 + 载荷 + 校验`。接收端需要限制最大总长、处理乱序/丢分片、超时释放缓存；不要仅靠“每次收到一段就拼到数组后面”。

## 8. 配对、绑定与权限

| 概念 | 解决的问题 | 注意点 |
| --- | --- | --- |
| Pairing（配对） | 建立安全关系、生成密钥 | 可能要求确认、输入或 OOB |
| Bonding（绑定） | 保存密钥，后续自动恢复安全连接 | 要考虑清除绑定和换手机流程 |
| Encryption（加密） | 空口数据保密 | 加密不自动等于授权合理 |
| Authentication（认证） | 降低中间人攻击风险 | Just Works 的 MITM 防护弱 |
| Attribute Permission | 对读写设置开放/加密/认证权限 | 敏感配置不能默认可写 |

安全设计的关键是先划分资产：设备控制、配网凭据、固件升级和日志分别需要什么权限。不要只因“蓝牙距离近”就把管理特征开放给所有扫描者；也不要在广播名、厂商数据或日志中暴露密钥、令牌和 Wi-Fi 密码。

## 9. 低功耗与连接状态机

```text
上电 -> 初始化协议栈 -> 广播中 -> 已连接 -> 发现/订阅完成 -> 业务收发
                           |            |                |
                           |            v                v
                           |         配对/加密        参数更新/低功耗
                           |            |                |
                           +--- 断开/超时/错误 <--------+
                                         |
                                         v
                                清理连接资源，按策略重新广播
```

低功耗不是只把 CPU `sleep`。广播间隔、扫描窗口、连接间隔、从机延迟、通知频率、传感器采样周期、日志和唤醒源要一起设计。典型策略是：未连接时低频广播；用户操作或配网窗口短时提高广播频率；连接后按交互需求更新连接参数；无交互后降低通知频率或主动断开。

## 10. 智能设备实现要点

### 10.1 收到写命令后的推荐路径

```text
GATT 写回调（尽快返回）
        |
        v
校验连接状态 / 长度 / 分包完整性 / 命令格式 / 权限
        |
        v
解析 requestId、命令类型、参数、版本
        |
        v
投递控制队列（不要在协议栈回调中做耗时硬件操作）
        |
        v
控制任务执行 -> 更新真实状态 -> Notify 状态或发送业务 ack
```

ATT 的 Write Response 只说明协议栈已接受这次写，不说明电机、GPIO 或存储操作已经成功。需要业务结果时，应通过状态特征或独立 ack 帧返回 `requestId`、结果码和真实状态。

### 10.2 Notify 与 Indicate 的选择

- 连续、可丢少量的传感器数据：通常用 Notify，并在应用层带序号。
- 关键配置结果、一次性状态变更：可用 Indicate，或 Notify + 应用层 ack/超时重传。
- 不论哪种方式，都要处理“Client 未订阅”“连接已断开”“发送队列满”和“手机后台限速”。

## 11. 看项目代码时，按这条路线走

| 顺序 | 在代码中搜索 | 想确认的问题 |
| --- | --- | --- |
| 1 | `ble`、`gap`、`gatt`、`nimble`、`bluedroid` | 使用哪套协议栈？初始化在何处？ |
| 2 | `advertising`、`adv_data`、`scan_rsp`、`UUID` | 广播名称/厂商数据/服务 UUID 是什么？何时启停？ |
| 3 | `connect`、`disconnect`、`conn_handle` | 多连接是否支持？断开后如何清理和重启广播？ |
| 4 | `service`、`characteristic`、`CCCD` | 有哪些服务和特征？属性权限是什么？ |
| 5 | `write_cb`、`read_cb`、`notify`、`indicate` | 数据从哪里进出？是否有队列和背压处理？ |
| 6 | `mtu`、`fragment`、`sequence`、`crc` | 大包如何分片、超时、校验和重传？ |
| 7 | `pair`、`bond`、`encrypt`、`passkey` | 哪些操作要求加密/认证？密钥如何清除？ |
| 8 | `conn_param`、`interval`、`latency`、`sleep` | 功耗与响应速度如何权衡？ |

建议把实际协议填入下表，避免只记住 UUID 而不知道业务语义：

| Service / Characteristic | UUID | 方向/属性 | 是否需加密 | Payload / 触发条件 | 处理模块 |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |

## 12. 伪代码：设备端最小骨架

```c
static int command_write_cb(uint16_t conn, const uint8_t *data, size_t len)
{
    if (!is_encrypted_if_required(conn) || parse_command_frame(data, len, &cmd) != 0)
        return ATT_ERROR_INVALID_PDU;

    command_queue_send(&cmd);       // 回调只校验和投递
    return 0;                        // 仅表示 GATT 写入已接收
}

static void control_task(void *arg)
{
    for (;;) {
        command_queue_receive(&cmd);
        result = apply_command_idempotently(&cmd);
        ble_notify(conn_handle, char_state, result.frame, result.len);
    }
}

static void gap_event_handler(gap_event_t event)
{
    if (event == BLE_CONNECTED) start_service_for_connection();
    if (event == BLE_DISCONNECTED) {
        clear_connection_state();
        start_advertising();
    }
}
```

真实 SDK API 不同，但职责边界应相同：GAP 负责连接生命周期，GATT 回调负责轻量收发，控制任务负责耗时业务，状态模块负责可信通知。

## 13. 常见问题与排查顺序

| 现象 | 优先检查 | 常见原因 |
| --- | --- | --- |
| 手机扫描不到 | 广播是否启动、名称/UUID、手机权限、距离、广播间隔 | 未启动广播；手机未授权蓝牙/定位；设备已被连接 |
| 能连上但找不到服务 | Service UUID、服务注册时机、缓存 | UUID/字节序理解错；App 使用了旧 GATT 缓存 |
| 写成功但设备没动作 | 写回调、业务帧解析、控制队列、业务 ack | 把 ATT 成功当业务成功；回调未投递 |
| 收不到通知 | 是否写 CCCD、当前连接、通知发送返回值 | Client 未订阅；断线后未重订阅；发送队列满 |
| 大数据丢失/错乱 | MTU 协商、分包序号、超时、缓冲区 | 按 20 字节假设不一致；无分包协议 |
| 频繁断开或耗电高 | RSSI、连接参数、射频干扰、日志/通知频率 | interval 过短；2.4 GHz 干扰；高频 Notify |
| 配对后仍无权限 | Attribute 权限、加密状态、绑定记录 | 仅配对未加密；旧绑定异常 |

排查日志至少包含：设备身份、连接句柄、事件类型、RSSI、MTU、连接参数、Service/Characteristic UUID、操作方向、长度、业务序号、错误码和断开原因。日志不要输出 Wi-Fi 密码、长期密钥或完整敏感数据。

## 14. 面试高频问答

### 14.1 BLE 与经典蓝牙有什么区别？

BLE 面向低功耗、短数据、快速发现和间歇连接；经典蓝牙常见于音频等持续数据场景。两者都属于蓝牙生态，但协议、功耗模型和常用 Profile 不同，不能只按“传输距离”区分。

### 14.2 GAP 与 GATT 分别做什么？

GAP 管发现、广播、连接、角色和安全过程；GATT 管连接后的 Attribute 数据模型和读写/通知访问。可理解为 GAP 负责“怎样遇见并连上”，GATT 负责“连上后怎样交换业务数据”。

### 14.3 Notify 和 Indicate 的区别？

Notify 没有逐包 ATT 确认，吞吐和实时性较好但要接受丢失/拥塞处理；Indicate 需要 Client 确认后才能继续，可靠性语义更强但速率更低。二者都不代替业务层的结果确认和幂等设计。

### 14.4 为什么默认单包常说只有 20 字节？

默认 ATT MTU 为 23 字节，扣除 ATT 头部后常见可用载荷为 20 字节。MTU 可以协商变大，但实际可用长度仍取决于双方、协议栈和链路能力，因此应用应有明确分包规则。

### 14.5 为什么 BLE 连接后还会断开？

可能是超出 supervision timeout、射频干扰、距离变化、手机系统策略、连接参数不合适、协议栈资源不足或主动断开。排查要结合 HCI/协议栈断开原因、RSSI、连接参数和业务负载，而不是只看 App 提示。

## 15. 复习清单

- 能画出“广播发现 -> 连接 -> 服务发现 -> 写/订阅 -> 通知”的数据流。
- 能区分 Central/Peripheral 与 GATT Client/Server。
- 能说明 Service、Characteristic、Descriptor 和 CCCD 的关系。
- 能解释 Read、Write、Notify、Indicate 的语义与边界。
- 能说明 MTU 不是吞吐保证，大包需要应用层分包。
- 能说明配对、绑定、加密和 Attribute 权限不是同一概念。
- 能按“广播 -> 连接 -> 服务 -> 回调 -> 队列 -> 通知 -> 断连/功耗/安全”阅读项目代码。

## 16. 回到实际项目时优先补全的信息

本文是通用框架，最终以项目的芯片、协议栈和手机 App 实现为准。优先拿到：广播名称与完整 AdvData、Service/Characteristic UUID 表、各特征属性与权限、连接/MTU 参数、业务帧格式和最大长度、Notify/Indicate 策略、配对绑定方案、断开原因统计与功耗目标。把这些填入第 11 节表格，才能形成真正可用于调试和面试的项目笔记。
