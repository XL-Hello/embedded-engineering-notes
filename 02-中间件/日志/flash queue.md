# Flash Queue：通用持久化数据队列方案

## 1. 目标与边界

Flash Queue 是一个运行在裸 Flash 上的**持久化 FIFO 数据队列**。它用于把高频采集数据先在 RAM 中汇聚，再压缩并顺序写入 Flash；网络可用时，按最旧优先的顺序上传，只有收到成功结果后才删除对应数据。

它不绑定具体芯片、RTOS、Flash 型号、网络协议或压缩算法。板级 Flash 地址、容量、擦除粒度、驱动接口，以及 RAM 缓冲数量和大小，都由使用者在配置和端口层提供。

范围：

- 支持高频数据采集、RAM 缓冲、压缩、Flash 持久化与 FIFO 上传。
- Flash 空间不足时，自动淘汰最旧且尚未上传的数据包，为新数据腾出空间。
- 支持掉电后的元数据恢复和数据包有效性校验。
- 只管理“数据包”的存取和状态，不负责传感器解析、网络协议、服务器确认格式或具体压缩实现。

数据流如下：

```text
采集源
  │
  ▼
高优先级采集任务 ──> 单/双/多 RAM RingBuffer
                            │
                            ▼
                     中优先级压缩落盘任务
                     取满缓冲 -> 压缩 -> 追加写 Flash
                                            │
                                            ▼
                              Flash Persistent FIFO Queue
                                            │
                                            ▼
                                  低优先级上传任务
                          读取最旧包 -> 上传 -> 成功确认 -> 删除
```

---

## 2. 功能需求

### 2.1 数据写入

1. 采集任务只负责快速写入 RAM RingBuffer，不直接擦写 Flash，也不执行压缩。
2. 当一个 RAM 缓冲达到配置阈值、收到显式 flush 请求或缓冲即将被切换时，将其交给压缩落盘任务。
3. 压缩落盘任务对一个完整批次按顺序执行：**取数 -> 压缩 -> 生成数据包 -> 写 Flash -> 提交元数据**。同一时刻只处理一个批次，保证压缩结果和 Flash 追加顺序一致。
4. 每次成功落盘形成一个可独立读取、校验、上传和删除的数据包。

### 2.2 数据上传与删除

1. 上传任务始终从 Flash 队列的最旧有效数据包开始读取。
2. 读取后调用用户提供的上传接口；接口必须能返回本次数据包是否已被服务端成功确认。
3. 仅在上传成功确认后删除该数据包、推进读指针并提交元数据。
4. 上传失败、超时、断网或设备复位时，不删除数据；下次继续从该最旧包重试。
5. 上传任务是低优先级任务，不得阻塞采集和压缩落盘。

### 2.3 空间与异常处理

1. 写入新包前必须判断 Flash 是否有足够连续/可用空间。
2. 空间不足时，从队列头部依次删除最旧包，直到能容纳新包；若新包本身超过整个数据区可用容量，写入失败并向调用方返回明确错误。
3. 启动时校验元数据；若元数据无效或不一致，扫描数据区恢复可识别的有效数据包。
4. 任何尚未完成提交的数据包不得被视为有效包，避免掉电后上传半包。

---

## 3. 可配置项

所有与产品相关的参数由使用者配置，组件内部不写死地址、容量、擦除大小、缓冲数量或算法。

```c
typedef struct {
    /* RAM 缓冲：ring_count 可为 1、2 或更多 */
    uint8_t  ring_count;
    void   **ring_mem;            // 用户提供的 RingBuffer 内存数组
    uint32_t *ring_size;          // 用户逐个配置每个 RingBuffer 的容量
    uint32_t flush_threshold;     // 触发落盘的有效数据阈值

    /* Flash 数据区域：均由用户按实际分区配置 */
    uint32_t flash_start_addr;
    uint32_t flash_size;
    uint32_t erase_unit_size;     // Flash 最小擦除单位
    uint32_t program_unit_size;   // Flash 最小写入/对齐单位；未知时由 port 处理

    /* 元数据区域；可位于数据区之外，也可在分区内预留 */
    uint32_t meta_a_addr;
    uint32_t meta_b_addr;
    uint32_t meta_size;

    uint32_t max_packet_size;
    uint32_t packet_align;
} flash_queue_cfg_t;
```

配置约束：

- `flash_start_addr` 与 `flash_size` 必须描述一块专属、可擦写的 Flash 区域，不能与程序、参数或其他模块重叠。
- `erase_unit_size` 必须等于底层 Flash 实际最小擦除单位；数据区和元数据区地址均应按此单位对齐。
- `program_unit_size`、`packet_align` 由底层写入要求决定；组件写入时补齐填充字节，但逻辑包长仍以包头字段为准。
- `ring_count` 支持单、双和多 RingBuffer；**每个 RingBuffer 的内存地址和大小均由用户逐个配置**，组件不分配固定大小的缓冲。
- `max_packet_size` 必须小于数据区可容纳的单包上限，并为包头、对齐和必要擦除预留空间。
- 所有 Flash、压缩、CRC、上传和 RingBuffer 操作均通过下面的端口接口注入；项目只定义接口契约，具体实现由用户适配。

---

## 4. 端口接口

Flash Queue 依赖用户实现硬件和业务接口。组件只调用接口，不直接访问芯片寄存器、文件系统或网络协议栈。

```c
/* 每个 RingBuffer 的具体实现由用户提供：可适配自研、RTOS 或第三方实现 */
typedef struct {
    int      (*init)(void *ring_mem, uint32_t ring_size, void **ring_handle);
    int      (*write)(void *ring_handle, const void *data, uint32_t len);
    uint32_t (*used)(void *ring_handle);
    int      (*seal)(void *ring_handle);  // 停止当前缓冲追加并移交落盘任务
    int      (*read)(void *ring_handle, uint32_t offset, void *buf, uint32_t len);
    int      (*reset)(void *ring_handle); // 落盘完成后复位为 FREE
} flash_queue_ring_ops_t;

typedef struct {
    int (*read)(uint32_t addr, void *buf, uint32_t len);
    int (*program)(uint32_t addr, const void *buf, uint32_t len);
    int (*erase)(uint32_t addr, uint32_t len);
    int (*sync)(void);            // 可选：等待异步驱动完成
} flash_queue_flash_ops_t;

typedef struct {
    int (*compress)(const void *src, uint32_t src_len,
                    void *dst, uint32_t dst_cap, uint32_t *dst_len);
    int (*upload)(const void *packet, uint32_t packet_len,
                  uint32_t seq); // 返回成功确认/失败/可重试状态
    uint32_t (*crc32)(const void *data, uint32_t len);
} flash_queue_user_ops_t;
```

接口约定：

- `ring_ops.init()` 对用户提供的每一组 `ring_mem[i]`、`ring_size[i]` 初始化一个 RingBuffer；`write/used/seal/read/reset` 定义组件与具体 RingBuffer 的唯一交互边界。
- 采集任务只调用 `ring_ops.write()` 和短路径状态切换；压缩落盘任务通过 `seal/read/reset` 取得完整批次并在落盘后归还缓冲。
- `program()` 必须遵守目标 Flash 的写入对齐、页写限制和“擦除后才能写”的规则；必要时由端口层分段处理。
- `erase()` 的地址和长度必须按 `erase_unit_size` 对齐。
- `upload()` 返回成功只表示服务端已确认该 `seq` 对应的数据包；网络发送成功但未收到业务确认时必须返回失败或待重试。
- 压缩接口可替换为 LZ4、无压缩透传或其他算法；若压缩后更大，可由配置策略选择透传原始数据或拒绝本批次。

---

## 5. 任务模型与 RAM RingBuffer

### 5.1 任务优先级

| 任务 | 建议优先级 | 职责 | 禁止事项 |
| --- | --- | --- | --- |
| 数据采集任务 | 高 | 接收/组包数据并快速写入当前 RAM RingBuffer | 压缩、擦除 Flash、等待网络 |
| 压缩写 Flash 任务 | 中 | 接收已封存缓冲，顺序压缩并追加写 Flash | 长时间等待网络 |
| 上传任务 | 低 | 读取最旧 Flash 包、上传、成功后删除 | 阻塞采集或并发删除未确认数据 |

任务之间使用 RTOS 队列、事件、信号量或等价机制交接“已封存缓冲”。采集任务对共享状态只做短临界区保护；Flash 读写、擦除和压缩均在中优先级任务中完成。

### 5.2 单、双、多 RingBuffer

```text
单缓冲：  采集/落盘不能真正重叠，适合低速或允许短暂停采集的场景。
双缓冲：  A 采集时，B 压缩落盘；A 满后切换，适合大多数持续采集场景。
多缓冲：  空闲缓冲池 -> 当前采集缓冲 -> 待处理队列 -> 落盘任务，
          可吸收短时数据高峰。
```

推荐状态机：

```text
FREE -> FILLING -> SEALED -> PROCESSING -> FREE
```

- 采集任务仅向 `FILLING` 缓冲追加数据。
- 达到阈值后，将该缓冲原子地标记为 `SEALED` 并投递给落盘任务；随后从 `FREE` 池获取下一个缓冲继续采集。
- 落盘任务处理 `SEALED` 缓冲时置为 `PROCESSING`；压缩与 Flash 提交均成功后释放为 `FREE`。
- 当没有空闲缓冲时，策略由用户选择：丢弃最新数据、丢弃最旧未落盘数据、短暂背压采集源或报告溢出。组件必须统计该事件，不能静默丢失。

缓冲数量估算应由用户完成。至少要覆盖：高峰期间产生的数据量，以及“压缩耗时 + Flash 擦写最坏耗时”期间继续进入的数据量。

---

## 6. Flash 队列布局

Flash 分为元数据区和数据区。物理大小及地址由配置提供，下面仅说明逻辑布局。

```text
+-------------------+  meta_a_addr
| Metadata A        |  一个或多个 erase unit
+-------------------+  meta_b_addr
| Metadata B        |  一个或多个 erase unit
+-------------------+  flash_start_addr
| Data Area         |  Packet 1, Packet 2, ...
|  Persistent Ring  |  可循环使用，按 erase unit 管理
+-------------------+  flash_start_addr + flash_size
```

数据区以逻辑环形队列方式使用：

```text
[tail] 最旧有效包  -->  ...有效包...  -->  [head] 下一个写入位置
```

- `tail` 指向最旧、尚未被删除的数据包。
- `head` 指向下一次追加写的位置。
- 新包只从 `head` 方向追加；删除和上传确认只从 `tail` 方向推进。
- 擦除以 `erase_unit_size` 为粒度：只有该擦除块内的所有数据包都已删除后，才能擦除并重新用于写入。
- 当 `head` 到达数据区末尾时，可回绕到起始位置，但只能写入已经释放并擦除的区域。

这样既保持 FIFO 顺序，也避免在仍含有效数据的擦除块上覆盖写入。

---

## 7. 数据包与提交格式

每个数据包应独立可识别、可校验、可跳过。建议采用“先写内容、最后提交”的格式。

```c
typedef struct {
    uint32_t magic;
    uint16_t header_size;
    uint16_t flags;          // 压缩方式、原始/压缩标志等
    uint32_t seq;            // 单调递增序号
    uint32_t timestamp;
    uint32_t raw_len;
    uint32_t payload_len;
    uint32_t payload_crc;
    uint32_t header_crc;
} flash_queue_packet_header_t;

/* payload 后追加 commit 标记，只有标记正确才表示该包有效 */
typedef struct {
    uint32_t magic;
    uint32_t seq;
    uint32_t packet_crc;
} flash_queue_packet_commit_t;
```

写入顺序：

```text
1. 选择并确认可写地址
2. 写 packet header
3. 写 payload 及对齐填充
4. 写 commit 标记
5. 校验必要字段并提交新的 Metadata
```

启动扫描时，只有同时满足以下条件的包才进入队列：`magic` 正确、长度合法且未越界、头部/负载 CRC 正确、`commit` 标记和 `seq` 匹配。写到一半断电的包没有有效 commit，扫描时直接忽略。

---

## 8. 元数据与掉电恢复

元数据保存队列运行状态，建议使用 A/B 双副本，并用版本号选择最新有效副本。

```c
typedef struct {
    uint32_t magic;
    uint32_t format_version;
    uint32_t generation;    // 每次成功提交递增
    uint32_t head;
    uint32_t tail;
    uint32_t packet_count;
    uint32_t next_seq;
    uint32_t crc;
} flash_queue_meta_t;
```

提交原则：

1. 先完成数据包的 commit，再写入新的元数据副本。
2. 新元数据写入空白/已擦除的副本区域，校验成功后才视为生效；不得原地覆盖唯一副本。
3. 启动时分别校验 A/B 的 `magic`、格式版本、地址范围和 CRC，选择 `generation` 最大的有效副本。
4. 若两个副本均无效，扫描数据区中连续的有效数据包，按 `seq` 和物理顺序重建 `head`、`tail`、包计数和 `next_seq`；恢复后写入新的元数据。

数据包写入成功但元数据尚未来得及更新时，扫描恢复应能发现该包；元数据先于数据包提交的顺序则禁止使用，以免出现指向半包的指针。

---

## 9. 关键执行流程

### 9.1 压缩并落盘

```text
等待 SEALED RAM 缓冲
  -> 读取该批原始数据
  -> 调用 compress()
  -> 计算最终数据包大小
  -> 确保可用空间（必要时从 tail 淘汰最旧包）
  -> 必要时擦除完全释放的 erase block
  -> 追加写 header / payload / commit
  -> 写入新的 A/B Metadata
  -> 释放 RAM 缓冲
```

空间不足时的淘汰流程：

```text
while (free_space < required_packet_space) {
    读取 tail 包头并校验长度；
    推进 tail 到下一包；
    若一个 erase block 已无有效包，则擦除该 block；
}
```

`required_packet_space` 应包括包头、有效载荷、commit 标记、写对齐填充，以及为回绕写入可能需要的边界处理空间。

### 9.2 上传最旧数据包

```text
等待网络可用或上传触发
  -> 查询 tail 是否存在有效包
  -> 读取并校验最旧包
  -> 调用 upload(payload, payload_len, seq)
  -> 收到成功确认：推进 tail，提交 Metadata，释放相应 erase block
  -> 失败/超时：保持 tail 不变，按用户策略延迟重试
```

上传过程不得提前删除包。若上传后设备掉电，下次可能重复上传同一 `seq`；服务端应以 `seq` 或业务唯一 ID 实现幂等去重。

---

## 10. 模块边界建议

```text
flash_queue/
├── flash_queue.c        队列状态机、写入/读取/删除流程
├── flash_queue_meta.c   A/B 元数据提交与恢复
├── flash_queue_packet.c 数据包编码、校验、扫描
├── flash_queue_ring.c   RAM RingBuffer 池与状态切换
├── flash_queue_port.h   Flash、压缩、CRC、上传等用户接口
└── flash_queue_cfg.h    用户配置结构和默认校验
```

对外建议提供以下抽象操作：

```c
int flash_queue_init(const flash_queue_cfg_t *cfg,
                     const flash_queue_ring_ops_t *ring_ops,
                     const flash_queue_flash_ops_t *flash_ops,
                     const flash_queue_user_ops_t *user_ops);

int flash_queue_collect(const void *data, uint32_t len);
int flash_queue_flush(void);
int flash_queue_process_pending(void);  // 由中优先级落盘任务调用
int flash_queue_upload_one(void);       // 由低优先级上传任务调用
int flash_queue_get_status(/* 用户定义统计输出 */);
```

`flash_queue_collect()` 应满足短路径、无 Flash I/O 的要求；`process_pending()` 和 `upload_one()` 应在各自任务上下文执行。

---

## 11. 状态、统计与错误处理

组件建议向使用者输出以下可观测信息：

- 当前有效包数、已用/可用 Flash 空间、`head`/`tail` 偏移。
- RAM 缓冲池的空闲数、待落盘数、采集溢出次数。
- 压缩成功/失败次数、压缩前后字节数、Flash 写入/擦除失败次数。
- 上传成功/失败/重试次数，以及因空间不足淘汰的最旧包数量。
- 元数据恢复路径：A/B 正常恢复、数据区扫描恢复、不可恢复错误。

出现 Flash 读写错误、长度非法、CRC 失败或元数据错误时，不应盲目推进指针。应保留故障原因并进入用户定义的处理策略，例如停止写入、只读保护、跳过损坏包或重新扫描恢复。

---

## 12. 设计要点汇总

- 采集任务高优先级、只写 RAM；压缩落盘任务中优先级、严格顺序执行；上传任务低优先级、只在成功确认后删除最旧包。
- 单、双、多 RingBuffer 都是有效配置：缓冲数量、每个缓冲的内存和大小均不是固定值，应由用户按数据高峰和最坏处理时延配置；RingBuffer 的初始化、写入、封存、读取和复位操作同样由用户实现并注入。
- Flash 起始地址、区域大小、最小擦除单位、写入对齐和底层读写擦接口全部由用户配置。
- Flash 数据包必须带长度、序号、校验与提交标记；元数据使用双副本，才能在掉电后可靠恢复。
- 删除是逻辑推进 `tail`，物理擦除必须按 Flash 擦除块进行；空间不足时按 FIFO 淘汰最旧数据。
- 上传遵循“读取 -> 上传 -> 成功确认 -> 删除”，并使用 `seq` 支持服务端幂等，防止断电重传造成重复处理。