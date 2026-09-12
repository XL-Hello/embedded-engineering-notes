# 裸 Flash 日志压缩包队列设计（300 KB / 4 KB 擦除块）

> 目标：把日志压缩包作为一个掉电可恢复、先进先出（FIFO）、可自动淘汰的持久化队列。本文不沿用任何既有日志方案。

## 1. 约束与结论

| 项目 | 设计值 |
|---|---:|
| Flash 可用区域 | 300 KB = 75 个 4 KB 擦除块 |
| 擦除粒度 | 4 KB |
| 控制区 | 2 个擦除块（8 KB，A/B 轮换元数据） |
| 数据区 | 73 个擦除块 = 292 KB |
| 单包原始长度 | 约 8~12 KB，不定长 |
| 单包实际占用 | `ceil((记录头 + payload) / 4096)`；通常 3~4 块 |
| 理论在队包数 | 通常约 18~24 包；以运行时 `package_count` 为准 |

关键点：Flash 不能把一个已写的字节改回 `0xFF`；因此“清除一个包”不是逐字节清零，而是**仅从队首删除整包占用的擦除块，再擦除这些块**。包必须按 4 KB 块对齐分配。

## 2. 区域布局

```text
300 KB Flash 区域
0x00000 +---------------------+ 4 KB  META A：元数据检查点/日志
        +---------------------+ 4 KB  META B：元数据检查点/日志
0x02000 +---------------------+
        |                     |
        |  DATA：73 个 4 KB 块  |  环形 FIFO，记录按块连续占用
        |                     |
0x4B000 +---------------------+
```

元数据区与数据区必须独立擦除。元数据只保存“快速启动提示”，数据记录自身才是最终事实来源；这样元数据在掉电时损坏也不会丢失已提交包。

## 3. 数据记录格式

每个压缩包从一个空闲 4 KB 块的起点开始，连续占用 `block_count` 个块；不要让一个包跨越数据区尾部回绕。

```c
#define LOG_MAGIC       0x4C504B47u  /* "LPKG" */
#define LOG_VERSION     1u

typedef enum {
    LOG_WRITING   = 0x7FFFFFFFu, // 仅已建立记录头
    LOG_COMMITTED = 0x3FFFFFFFu, // payload、CRC 均已写完，可读取
    LOG_OBSOLETE  = 0x1FFFFFFFu, // 已删除，仅作为掉电恢复标志
} log_state_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t header_size;
    uint32_t state;          // 最后单独写入；Flash 位只从 1 变 0
    uint64_t sequence;       // 全局递增，决定“最旧”
    uint32_t payload_len;    // 压缩包实际长度
    uint16_t block_count;    // 本记录总共占用的 4 KB 块数
    uint16_t flags;          // bit0: PAD（尾部填充记录）
    uint32_t payload_crc32;
    uint32_t header_crc32;   // 覆盖 state 以外的头字段
} log_record_header_t;
```

`block_count = ceil((sizeof(header) + payload_len) / 4096)`。payload 紧接记录头存放，剩余空间保持 `0xFF` 即可。记录头建议固定在首块前 64~128 B，便于扫描。

### 提交顺序（掉电安全）

1. 在已擦除块写入头，`state=LOG_WRITING`，并写好长度、块数、序号和 CRC 字段。
2. 写入完整 payload。
3. 读回校验 payload CRC（或硬件写后校验）。
4. **最后**仅把 `state` 编程为 `LOG_COMMITTED`。
5. 进入 RAM 索引，`package_count++`，发出“有新日志”事件。

掉电时遇到 `WRITING`、头 CRC 错误、长度越界或 payload CRC 错误，均视为未提交垃圾；启动恢复时擦除它及其后的可安全回收区域，绝不把它计入数量。

## 4. RAM 队列与元数据

RAM 维护一个长度最多 73 的描述符环（一个描述符对应一个包）：

```c
typedef struct {
    uint16_t start_block;     // DATA 区相对块号
    uint16_t block_count;
    uint32_t payload_len;
    uint64_t sequence;
    uint32_t payload_crc32;
    bool     uploading;       // 防止两个上传者同时取同一包
} log_desc_t;
```

提供 `package_count`（受锁保护）作为 O(1) 查询结果；上传线程不需要扫描 Flash。启动或异常恢复时才线性扫描最多 73 个块，按 `sequence` 重建 FIFO，因此即使元数据失效也很快。

META A/B 采用轮换检查点，各自含 `generation、head_block、tail_block、next_sequence、package_count、crc32、valid_mark`。每成功写入/删除一包即可追加一条小型 journal；journal 满再擦除另一 META 块并写一份完整快照。它的用途是缩短启动恢复，不作为唯一真相。`valid_mark` 同样最后从 1 写成 0。

## 5. 核心接口与并发模型

```c
int logq_init(void);                              // 启动恢复
uint16_t logq_count(void);                        // O(1)，返回已提交包数
int logq_push(const uint8_t *data, uint32_t len); // 写入一个压缩包
int logq_peek_oldest(log_handle_t *h);            // 领取最旧包（不删除）
int logq_read(const log_handle_t *h, uint8_t *buf, uint32_t cap,
              uint32_t *actual_len);
int logq_ack_delete(const log_handle_t *h);       // 上传成功后删除
void logq_release(const log_handle_t *h);         // 上传失败，取消领取
```

所有会改变队列结构的操作均在同一个 `logq_mutex` 下执行：`push / peek / ack_delete / init-recover`。Flash 擦除或大 payload 写入较慢，锁内不要等待网络；上传流程只在锁内领取描述符，随后解锁读取和发送，最后短暂加锁确认删除。

`log_handle_t` 至少携带 `sequence` 和 `start_block`。`ack_delete()` 必须复核它仍是队首且 `uploading=true`，防止旧句柄误删新包。

## 6. 写入与满盘自动淘汰

### 6.1 `logq_push()` 伪代码

```text
need = ceil((header_size + len) / 4096)
若 len 非法，或 need > DATA_BLOCKS：失败（此包物理上放不下）

lock(logq_mutex)
若 tail 到数据区末尾的连续空闲块 < need：
    写一个已提交 PAD 记录占满尾部剩余块；tail 回到 0

while 连续空闲块 < need：
    若队列为空：报告内部状态异常并重新初始化空区
    若队首包正被 uploading：不能删除正在上传的数据，返回 EBUSY/ENOSPC
    remove_head_locked(reason=SPACE_PRESSURE)  // 标 obsolete，擦除其全部块，count--

在 tail 的已擦除连续块完成 WRITING -> payload -> CRC -> COMMITTED
尾指针前移；count++；写 meta journal；unlock
set_event(LOGQ_EVENT_NONEMPTY)
```

这里的“连续空闲块”要同时考虑环形地址和头指针，不能只用总空闲字节。使用 PAD 避免包跨边界，恢复扫描时 PAD 不计数并直接把扫描位置跳回块 0。

### 6.2 队首删除

`remove_head_locked()` 按下面顺序执行：

1. 将队首记录状态由 `COMMITTED` 编程为 `OBSOLETE`；
2. 更新 RAM 队首和 `package_count--`，写 meta journal；
3. 擦除该记录的全部 `block_count` 块；
4. 若它后面是 PAD，擦除 PAD 块并把 head 回绕到 0。

步骤 1 后掉电：恢复时该包已不可见，可安全擦除；步骤 2/3 后掉电：扫描也能识别已删除记录及空块。为保证新包绝不会覆盖尚未擦除的数据，`push` 只接受读回确认为全 `0xFF` 的块。

**上传中的队首不可因空间压力自动删除。**这是数据可靠性的必要取舍：若存储已满且唯一最旧包正在上传，`push` 返回 `EBUSY`，由日志生产者丢弃本次新包/稍后重试。若业务允许“新日志优先”，可配置 `LOGQ_EVICT_INFLIGHT`，先取消上传句柄再淘汰它，但必须明确接受上传失败和旧包丢失。

## 7. 两个 RTOS 线程

```text
日志生成线程（不定时）                         上传线程（可未创建/可停止）
compress -> logq_push() --- event/semaphore ---> 等待唤醒或周期超时
                                                     |
                                            count()==0 ? 跳过
                                                     |
                                       peek_oldest -> read -> 上传网络
                                                     |
                                成功：ack_delete；失败：release + 退避重试
```

### 写线程

- 压缩完成后调用 `logq_push()`；不持有网络资源。
- 写入成功后调用 `xEventGroupSetBits(LOGQ_EVENT_NONEMPTY)` 或 `xSemaphoreGive()`。
- `EBUSY/ENOSPC` 记录 RAM 统计与告警，不在高优先级任务里长时间循环重试。

### 上传线程

- 线程可能被关闭：这是合法状态，Flash 队列仍持续积压并按满盘策略淘汰最旧包。
- 运行时以事件唤醒，同时每 N 秒超时醒来一次，防止事件丢失；启动后先检查 `logq_count()`。
- 成功上传才 `ack_delete()`；HTTP/MQTT 发送失败、断网或服务器未确认均 `release()`，保留包等待下次。
- 一次只领取一包；读取到独立 RAM 上传缓冲区后再联网。若 RAM 不够，可分片读取，但整个上传期保持领取标记。
- 停止线程前执行 `release()`，不得带着 `uploading=true` 退出；若发生异常复位，`logq_init()` 清除 RAM lease，包仍保持 committed，供下次继续上传。

## 8. 启动恢复流程

1. 读取 META A/B，选择 CRC 正确且 `generation` 最大的检查点。
2. 从检查点给出的 head 开始验证每条记录：magic、header CRC、块数范围、序号连续性和 payload CRC。
3. 对 `COMMITTED` 记录入 RAM FIFO；`OBSOLETE` 跳过；PAD 执行回绕；遇到空块停止。
4. 遇到 `WRITING` 或损坏记录时，不计数，擦除该条及其后未提交尾部；保留此前已提交记录。
5. 用扫描结果覆盖元数据提示，写入新的完整检查点；若 count>0，置位 `NONEMPTY` 事件。

若启动时间要求极严，可只做头 CRC 和长度检查，把 payload CRC 延迟到 `peek/read`；若日志可靠性优先，启动即校验 payload CRC（总区仅 300 KB，代价很低）。

## 9. 必须明确的边界与测试

- **容量不是按 300 KB / 平均包长直接计算。**4 KB 对齐和记录头使 8 KB 包占 3 块、12 KB 包通常占 4 块。
- 压缩包最大长度必须限制为 `DATA_SIZE - sizeof(header)`，并设业务上限，防止畸形长度破坏扫描。
- Flash 擦除次数有限：环形 FIFO 已均衡数据区磨损；META A/B journal 可降低元数据擦除频率。若芯片支持，写/擦后应使用驱动返回值和读回校验。
- 供电故障测试至少覆盖：写头后、写 payload 中、写完 payload 未提交、提交后未写 meta、标 obsolete 后、擦除中、PAD 写入中。
- 并发测试至少覆盖：上传持有队首时连续写满；上传失败后重试；上传线程停用数天后重新启用；写线程与 ack 同时到达。

## 10. 推荐默认策略

1. 默认“保留正在上传的最旧包”，空间不足时 `push` 短暂失败，而非中断上传。
2. 上传成功收到业务侧明确 ACK 后才删除；TCP/HTTP 写成功本身不等价于服务端持久化成功。
3. RAM 索引作为快速路径，记录头 + CRC 作为掉电恢复依据，A/B 元数据作为启动加速器。
4. 生产版本增加统计：`push_ok / push_drop_full / evict_count / upload_ok / upload_fail / recover_discard`，方便定位日志为何丢失。

