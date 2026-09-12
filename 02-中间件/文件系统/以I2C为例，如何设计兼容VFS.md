# 以 I2C 为例：如何设计兼容 VFS 的嵌入式驱动

> 目标：理解 **VFS 如何把上层访问统一起来**，以及 I2C 驱动怎样接入这一套机制。本文不讨论 I2C 时序、电气特性和寄存器位定义。

## 先说结论

“兼容 VFS”不是让 I2C 总线变成文件系统，而是让用户态或上层组件可以用一组统一的文件式操作访问某个驱动入口：

```text
open / read / write / ioctl / poll / close
```

I2C、UART、SPI 等都可以采用相似的分层思路：**VFS 负责统一入口和对象生命周期；设备类驱动负责解释文件操作；总线/控制器驱动负责真正传输；设备驱动负责某颗芯片的语义。**

但“相似”不代表接口细节完全相同。设计 VFS 适配层前，先区分设备传输的自然数据模型：

### 字节流、事务与帧

- **UART 是字节流**：硬件连续交付一个个字节，没有天然的“这一组字节从哪里开始、到哪里结束”的边界。即使连续发送 `0x01、0x02、0x03`，接收端看到的仍只是 3 个依次到达的字节；分包必须由软件通过包头、长度、校验、换行符或超时等协议完成。因此 VFS 中通常使用 `/dev/tty*` 的 `read/write/poll`，配合 RX/TX 环形缓冲区、流控和协议解析。
- **I2C/SPI 是事务**：一组字节被硬件边界包裹成一次访问。I2C 以 `START` 到 `STOP`（中间包含地址、读写位和 ACK）界定事务；SPI 通常以 `CS` 拉低到拉高界定事务。一次事务可以包含多个阶段，例如 I2C 传感器的“写寄存器地址后重复起始再读数据”。因此 VFS 的 `read/write` 不应被误解为任意字节流，驱动内部要保证一次组合消息的原子性，复杂配置或原始总线访问可使用 `ioctl` 或专用传输接口。
- **MIPI CSI/DSI 更接近帧/队列模型**：CSI 接收摄像头图像帧，DSI 向显示面板发送显示命令或像素数据；实际工作通常由 DMA 把数据放入多个缓冲区，再通过队列完成“提交—传输—完成—回收”。上层还要处理帧格式、分辨率、时间戳、带宽、同步和 buffer ownership。这类设备通常接入 V4L2、DRM/KMS 等专用子系统，使用 `mmap`、`QBUF/DQBUF` 或 page-flip 一类的队列接口，而不是简单地把每帧都当作普通 `read`。

可以这样记忆：**UART 的边界由软件协议补上，I2C/SPI 的边界由总线事务给出，MIPI 的边界通常是帧和缓冲队列。** 所以 VFS 统一的是 `open/read/write/ioctl/poll/close` 这些访问入口，不是把所有硬件都强行抽象成“读写一串字节”。以 I2C 为例，功能驱动应把“读取一次传感器样本”建模为一次完整事务；`poll` 等待的是样本已就绪或异步事务完成，而不是每次轮询都重新发起 I2C 读操作。

---

## 1. 为什么需要 VFS

没有 VFS 时，每个驱动可能暴露不同的调用方式：

```c
i2c_transfer(bus, msgs, n);
uart_recv(port, buf, len);
sensor_read_reg(dev, reg, buf, len);
```

这样直接调用很高效，但上层需要知道具体总线、控制器和对象类型。系统变大后会出现几个问题：

- 应用或中间件要为每类设备学习不同接口；
- 权限、命名、阻塞/非阻塞、并发和资源释放容易重复实现；
- `select` / `poll` / `epoll` 等等待机制无法自然复用；
- 驱动替换或设备热插拔时，上层耦合很深。

VFS（Virtual File System，虚拟文件系统）把“**如何找到并操作一个内核对象**”统一成文件描述符（fd）及文件操作。它不要求底层一定是磁盘文件；字符设备、管道、socket 都可以成为 VFS 节点。

因此，VFS 的价值是统一 **访问模型**，不是统一 **硬件协议**。

---

## 2. 先分清四个角色

以一个 I2C 温度传感器为例，最容易混淆的是下面几层：

```text
应用 / 服务
  │ open("/dev/temp0")、read(fd, ...)、ioctl(fd, ...)
  ▼
VFS：路径、inode、file、fd、权限、引用计数、阻塞语义
  ▼
设备节点对应的 file_operations（字符设备或框架入口）
  ▼
传感器驱动：温度单位、采样频率、寄存器含义、缓存策略
  ▼
I2C 核心/适配器：寻址、消息组合、互斥、超时、重试
  ▼
I2C 控制器驱动：DMA/中断/寄存器/FIFO
  ▼
I2C 总线上的温度传感器
```

| 层 | 主要职责 | 不应承担的职责 |
| --- | --- | --- |
| VFS | 将路径变为 `file`，转发 `read/write/ioctl/poll` | 知道 I2C 地址或寄存器含义 |
| 字符设备/设备类接口 | 定义用户可见 ABI，做参数校验与拷贝 | 直接操作控制器寄存器 |
| 具体设备驱动 | 设备功能、单位换算、状态机 | 管理全局路径解析 |
| I2C 核心与控制器 | 完成一笔 I2C 传输 | 把传感器原始数据解释成温度 |

关键点：`/dev/temp0` 代表的是“温度功能”，不一定代表“某条 I2C 总线”。同一颗 I2C 芯片也可以暴露为 input、IIO、RTC、LED 等不同内核子系统，而非一个通用字符设备。

---

## 3. VFS 视角：一次访问发生了什么

以下以 Linux 风格概念说明，RT-Thread、NuttX、Zephyr 等 RTOS 名称不同，但思想相近。

```text
open("/dev/temp0")
  → VFS 按路径找到设备节点
  → 创建 struct file，返回 fd
  → 调用驱动的 open（可选）

read(fd, user_buf, len)
  → VFS 根据 file 找到 file_operations
  → 调用驱动的 read
  → 驱动读取缓存，或发起一次 I2C 事务
  → 将结果安全复制给用户态

close(fd)
  → 引用计数减少
  → 最后一个引用释放时，调用 release（可选）
```

典型操作集可抽象为：

```c
struct file_operations {
    int     (*open)(struct inode *inode, struct file *file);
    ssize_t (*read)(struct file *file, char __user *buf, size_t len, loff_t *pos);
    ssize_t (*write)(struct file *file, const char __user *buf, size_t len, loff_t *pos);
    long    (*unlocked_ioctl)(struct file *file, unsigned int cmd, unsigned long arg);
    __poll_t(*poll)(struct file *file, poll_table *wait);
    int     (*release)(struct inode *inode, struct file *file);
};
```

并非每项都必须实现。一个只读传感器通常实现 `read`、`ioctl`、`poll`、`release`；不支持的操作应明确返回合适错误，而不是悄悄成功。

---

## 4. 推荐的 I2C 分层设计

### 4.1 控制器层：只关心“怎样传输”

该层匹配 SoC 中的 I2C 控制器。它实现启动 DMA/中断、等待完成、异常恢复等硬件差异，并向上提供统一的适配器能力：

```c
int i2c_adapter_xfer(struct i2c_adapter *adap,
                     struct i2c_msg *msgs, int num);
```

不要在这里写某个温度计、EEPROM 的寄存器定义，更不要创建 `/dev/temp0`。

### 4.2 I2C 核心层：只关心“怎样组织事务”

上层用 `i2c_msg` 描述读写方向、从地址、缓冲区与长度。核心层选择适配器、串行化访问、检查能力，并调用控制器层。

例如“先写寄存器地址，再重复起始读数据”在此层仍是一笔组合事务；对设备驱动而言，它不必知道 FIFO 或中断细节。

```c
int reg_read(struct my_i2c_dev *dev, u8 reg, u8 *data, size_t n)
{
    struct i2c_msg msgs[2] = {
        { .addr = dev->addr, .flags = 0,        .buf = &reg,  .len = 1 },
        { .addr = dev->addr, .flags = I2C_M_RD, .buf = data,  .len = n },
    };
    return i2c_transfer(dev->client->adapter, msgs, 2);
}
```

### 4.3 设备功能层：把“芯片协议”变成“业务能力”

这是温度传感器驱动应在的位置。它负责 probe/remove、电源管理、设备状态、寄存器解释与缓存。它对上导出的是有意义的能力，例如 `read_temperature()`，而不是让每个应用自行拼寄存器读写。

```c
int temp_read_millicelsius(struct temp_dev *dev, int *mc)
{
    u8 raw[2];
    int ret = reg_read(&dev->i2c, TEMP_REG_VALUE, raw, sizeof(raw));
    if (ret < 0)
        return ret;
    *mc = decode_temperature(raw);
    return 0;
}
```

### 4.4 VFS 适配层：定义稳定、克制的用户 ABI

VFS 入口可以由设备功能层直接实现，也可以由对应的子系统统一提供。若需要自定义字符设备，建议把 VFS 回调写得很薄：

```c
static ssize_t temp_read(struct file *file, char __user *buf,
                         size_t len, loff_t *pos)
{
    struct temp_dev *dev = file->private_data;
    struct temp_sample sample;
    int ret;

    if (len < sizeof(sample))
        return -EINVAL;

    ret = temp_get_sample(dev, &sample);   // 可能读取缓存，也可能触发 I2C
    if (ret)
        return ret;
    if (copy_to_user(buf, &sample, sizeof(sample)))
        return -EFAULT;
    return sizeof(sample);
}
```

这里的 `read` 不应直接把“任意 I2C 地址 + 任意寄存器 + 任意长度”开放给不受信任应用。那是调试/原型接口，不是稳定产品 ABI；它会绕过设备语义、访问控制和并发约束。

---

## 5. `read`、`write` 与 `ioctl` 应如何分工

一个简单规则：**频繁传递的数据走 `read/write`；少量控制命令走 `ioctl`；可枚举的配置尽量走标准属性/子系统接口。**

| 操作 | 适合内容 | 例子 |
| --- | --- | --- |
| `read` | 连续或可采样的数据 | 读取一条温度样本、接收 UART 字节 |
| `write` | 数据流或命令负载 | 发送 UART 数据、SPI 写帧 |
| `ioctl` | 不适合字节流表达的控制 | 设置采样率、启动一次采集、获取统计信息 |
| `poll` | 告知“现在读/写是否会阻塞” | 新样本到达、串口收到数据、队列可写 |
| `mmap` | 大块、持续的共享缓冲 | 摄像头帧、DMA 环形缓冲；普通 I2C 传感器通常不需要 |

`ioctl` 是 ABI，不是万能逃生门。每个命令需要固定编号、明确输入输出结构体、版本/尺寸校验，并考虑 32/64 位兼容。若调用频繁、参数复杂，考虑 netlink、sysfs、configfs 或专用子系统接口，而不是不断堆叠 ioctl。

---

## 6. `poll`：就绪探测与多路阻塞等待

### 6.1 一句话结论

`poll` 不是单纯的“判断函数”，而是一套**探测多个 fd 的就绪状态，并在没有事件时阻塞等待**的同步机制。它的优势不是“当前任务不阻塞”，而是：**当前任务在无事件时主动休眠、让出 CPU，从而避免忙轮询。**

这里必须区分两个概念：

- **任务阻塞**：当前任务等待数据、空间、错误或超时；这是 `poll` 的正常行为。
- **CPU 忙等**：任务不断运行、不断查询、却没有有用工作；这是 `poll` 要避免的情况。

因此，`poll(fds, nfds, -1)` 在没有任何 fd 就绪时会阻塞调用者，但不会让 CPU 空转；调度器可运行其他任务，或让 CPU 进入空闲状态。

### 6.2 调用者看到的三种超时语义

| 调用 | 行为 | 典型用途 |
| --- | --- | --- |
| `poll(fds, nfds, 0)` | 仅立即探测一次，立刻返回，不休眠 | 周期性巡检、已有主循环且不希望等待 |
| `poll(fds, nfds, 100)` | 最多等待 100 ms；任一 fd 就绪则提前返回 | 等待事件，同时周期性处理保活/超时任务 |
| `poll(fds, nfds, -1)` | 一直等待，直到事件、信号或错误使其返回 | 常规事件循环、串口接收线程 |

返回值大于 0 表示至少一个 `pollfd.revents` 有事件；返回 0 表示超时；返回负值表示调用失败或被信号中断（具体错误码依系统而定）。应用必须检查每个 fd 的 `revents`，不能只因为返回值大于 0 就假定所有 fd 都可读。

### 6.3 与忙轮询的区别：以 UART 为例

若 fd 被设为非阻塞，下面的写法会不断消耗 CPU：

```c
for (;;) {
    ssize_t n = read(fd, buf, sizeof(buf));
    if (n > 0)
        handle_uart_data(buf, n);
    // n == -1 && errno == EAGAIN 时立刻再次 read，形成忙轮询
}
```

使用 `poll` 时，事件循环只在数据可能可读时才调用 `read`：

```c
struct pollfd pfd = {
    .fd = uart_fd,
    .events = POLLIN,
};

for (;;) {
    int ret = poll(&pfd, 1, -1);
    if (ret > 0 && (pfd.revents & POLLIN)) {
        ssize_t n = read(uart_fd, buf, sizeof(buf));
        if (n > 0)
            handle_uart_data(buf, n);
    }
}
```

等待期间调用线程处于休眠状态；CPU 可以执行其他任务。`poll` 同时接受多个 `pollfd`，所以一个线程可等待多路 UART、管道、socket 或其他支持 VFS `poll` 的设备，而不必为每个设备各自创建忙轮询线程。

### 6.4 底层模型：驱动回调负责“登记 + 报告”，不是在回调里睡眠

以 Linux 风格的 VFS `file_operations.poll(file, wait)` 为例，完整流程应理解为：

```text
应用 poll(fds, nfds, timeout)
  │
  ├─ VFS/poll 核心依次调用每个 fd 的 .poll 回调
  │    ├─ 驱动将当前等待者登记到自己的等待队列（poll_wait）
  │    └─ 驱动快速检查缓存/FIFO/错误状态，返回 POLLIN、POLLOUT、POLLERR…
  │
  ├─ 若任一 fd 已就绪：poll 立即返回
  └─ 若均未就绪且 timeout ≠ 0：poll 核心让调用任务休眠
       │
       ├─ UART RX 中断把字节放入 RX 缓冲，并唤醒等待队列
       ├─ 或其他任务写入数据、释放 TX 空间、设备报错/断开
       └─ 或等待超时
            │
            └─ poll 核心重新检查就绪状态并返回给应用
```

这里的边界非常重要：**`.poll` 回调应短小、不可阻塞。** 它的工作是把等待者关联到设备等待队列并报告“此刻”的状态；真正把当前任务挂起的是 VFS/`poll` 核心在检查全部 fd 之后的统一逻辑。驱动在 UART 中断或其他状态变化路径中，通过平台的等待队列/事件对象唤醒等待者。

这样安排还避免一个经典竞态：若驱动先检查“没有数据”，再单独进入休眠，恰好在两步之间收到一个字节，唤醒可能被错过。标准 `poll_wait` 机制把等待登记与状态检查纳入同一协议；驱动状态改变时再唤醒，VFS 核心会复查状态。

不同 RTOS 的 VFS 接口名称和实现可能不同：有的通过等待队列，有的通过信号量、事件组或驱动事件回调；有的精简 VFS 仅支持立即探测。设计前必须确认目标系统的 VFS 是否真的实现了阻塞式 `poll` 及驱动唤醒接口，不能把 Linux 的 `poll_table` 代码直接照搬到所有平台。

### 6.5 就绪是“建议现在尝试”，不是数据所有权

`POLLIN` 的含义是“**现在尝试 `read` 通常不会阻塞**”，而不是“数据已经自动交给应用”。`poll` 不会读取 RX FIFO 或消费驱动缓存；收到 `POLLIN` 后应调用 `read` 取走数据。若不读取，数据仍留在缓冲区，下一次 `poll` 仍可能持续报告 `POLLIN`。

同样，`POLLOUT` 表示“现在通常可以接受一些写入”，不是保证任意长度的 `write` 都能完整成功。多个线程/进程共享 fd、另一消费者抢先读走数据、设备断开或状态变化，都可能让 `poll` 返回后实际 `read/write` 的结果改变。因此稳健代码应：

- 即使先收到 `POLLIN`，也正确处理 `read` 的短读、返回 0 和 `-EAGAIN`。
- 即使先收到 `POLLOUT`，也处理短写、`-EAGAIN` 和 I/O 错误。
- 关注 `POLLERR`、`POLLHUP`、`POLLNVAL` 等异常/关闭事件；它们不应被当成普通可读事件忽略。

这也是事件循环常将 fd 设为非阻塞的原因：从 `poll` 返回到实际 `read/write` 之间，状态允许变化；非阻塞 I/O 能保证竞态发生时返回 `-EAGAIN`，而不是意外再次卡住。

### 6.6 面向 I2C 设备时，先定义“何时可读”

I2C 是事务总线，通常不像 UART 一样天然持续产生字节流。因此一个 I2C 设备的 `poll` 语义必须由其**功能层**定义，例如：新传感器样本已进入缓存、转换完成引脚触发、测量任务完成，或异步请求已结束。

不应把“每次 `poll` 都发一笔 I2C 读寄存器事务”作为默认实现：这会使探测变慢、带来总线流量和副作用，也破坏 `poll` 回调应快速返回的原则。更合理的结构是由中断、定时采样任务或异步 I2C 完成回调更新缓存和就绪标志，再唤醒等待者；`read` 取缓存，或按已明确的 ABI 发起同步采样。

对没有异步事件、只提供按需读寄存器能力的简单 I2C 设备，完全可以不实现阻塞式 `poll`，或只定义始终可读的语义。是否实现应由用户可见的数据模型决定，而不是因为 VFS 存在 `poll` 槽位就机械实现。

---

## 7. 生命周期、并发与错误处理

这些往往比“能读到寄存器”更决定驱动是否可靠。

### 生命周期

1. 控制器驱动注册 I2C adapter。
2. 设备被枚举（设备树、ACPI、板级表或动态创建），生成 I2C client。
3. 设备驱动 `probe`：确认芯片、初始化资源、注册其对外接口/设备节点。
4. 应用 `open` 后，`file->private_data` 保存设备上下文，必要时增加引用。
5. `remove`/热拔出时禁止新 I/O，并让已打开 fd 得到可预期错误；不能在仍有 I/O 或 fd 引用时释放内存。

### 并发

- I2C 总线是共享资源：事务通常需要适配器层序列化。
- 设备自身状态（缓存、配置、错误状态）需要锁保护。
- 不能持有自旋锁后睡眠等待 I2C 完成；通常使用 mutex、completion、工作队列等合适原语。
- `read` 若可能长时间等待，需定义阻塞、`O_NONBLOCK` 和 `poll` 的行为。

### 错误

应保留对上层有价值的错误：参数错误 `-EINVAL`、未连接/无设备 `-ENXIO` 或 `-ENODEV`、超时 `-ETIMEDOUT`、不可恢复 I/O 故障 `-EIO`、非阻塞时无数据 `-EAGAIN`。不要把所有失败都压成“返回 0”。

---

## 8. 一个完整的调用路径

```text
用户：read(fd_temp, &sample, sizeof(sample))
  ↓
VFS：根据 fd 调用 temp_fops.read
  ↓
温度驱动：检查状态与缓存；必要时调用 temp_read_millicelsius
  ↓
I2C 核心：形成读寄存器的消息集合，选择对应 adapter
  ↓
I2C 控制器：启动传输，等待中断/DMA 完成，报告结果
  ↓
温度驱动：解码原始值，填充 sample，copy_to_user
  ↓
VFS：把字节数或 errno 返回给用户
```

这条路径体现了最重要的依赖方向：**上层只依赖抽象，下层不依赖 VFS 的业务语义。** 更换 I2C 控制器，不应要求修改温度驱动；同一温度芯片改用 SPI 版本时，也应尽量复用温度功能层。

---

## 9. UART、SPI、MIPI 是否也是一个思路？

总体上是：都可以接入 VFS，遵循“统一入口 + 设备语义 + 传输实现”的分层。但它们的自然用户接口不同。

| 类型 | 数据本质 | 常见 VFS 形态 | 与 I2C 的关键不同 |
| --- | --- | --- | --- |
| I2C | 有地址的短事务 | 具体设备的字符设备/传感器子系统；调试时可有 `/dev/i2c-X` | 总线共享，常需原子组合消息 |
| SPI | 片选边界内的全双工事务 | `ioctl` 配置模式/速率，`read/write` 或一次传输接口；具体设备通常有专用驱动 | 无总线寻址、全双工、片选和传输边界重要 |
| UART | 连续字节流 | `/dev/tty*`，天然使用 `read/write/poll` | 没有“单次寄存器事务”的天然边界，需处理缓冲、行规程、流控 |
| MIPI CSI/DSI | 帧流或显示命令链 | V4L2、DRM/KMS 等专用子系统，常伴随 `mmap`/队列 | 带宽高、DMA 缓冲和帧时序关键，不宜只用普通 `read` |

因此不能机械地把所有硬件都设计成“`read` 一个寄存器、`write` 一个寄存器”。正确做法是：

1. 先识别设备提供的是字节流、事务、事件、帧还是控制属性；
2. 优先接入已有内核/RTOS 子系统（TTY、IIO、input、V4L2、DRM、RTC、MTD……）；
3. 只有现有子系统不合适时，才设计自定义字符设备 ABI；
4. 无论采用何种接口，底层传输都与用户 ABI 解耦。

---

## 10. 常见误区

### 误区 1：有 `/dev/i2c-1` 就等于完成了产品驱动

`/dev/i2c-1` 这种通用节点便于调试和工具访问，但上层仍需要知道从地址、寄存器格式、字节序和时序约束。产品功能驱动应进一步抽象这些细节。

### 误区 2：VFS 只能用于用户态

VFS 主要提供用户态/内核对象边界，但内核内部也可以通过统一框架组织设备。是否暴露设备节点是 ABI 设计决定，不是硬性要求。

### 误区 3：`read()` 必须每次都访问硬件

不一定。传感器可以由定时任务或中断刷新缓存，`read` 只取最新样本；也可规定 `read` 触发同步采样。关键是把语义写清楚。

### 误区 4：自定义 ioctl 越多越灵活

过多 ioctl 会让 ABI 难维护。优先使用明确的数据结构、版本化与标准子系统接口，并限制原始寄存器访问。

---

## 11. 设计检查清单

- [ ] 用户看到的节点表示“功能”，而不是泄漏不必要的总线细节。
- [ ] `read/write/ioctl/poll` 的数据格式、阻塞行为和错误码已定义。
- [ ] 用户指针访问经过安全校验/拷贝；长度和溢出得到检查。
- [ ] I2C 总线并发、设备状态并发、休眠上下文均已考虑。
- [ ] open fd、设备移除和电源管理不会造成悬空指针或死锁。
- [ ] I2C 控制器差异没有渗入设备功能层。
- [ ] 优先复用 TTY/IIO/input/V4L2/DRM 等成熟子系统，而不是重复发明 ABI。
- [ ] 调试原始访问接口和稳定产品接口分离，并有权限控制。

## 小结

VFS 的核心思想是把“访问对象”统一为文件操作，而把“对象如何完成工作”留给各层驱动。对 I2C 来说，最健康的结构通常是：

```text
VFS/设备类接口 → 具体芯片功能驱动 → I2C 核心 → I2C 控制器驱动
```

同样的分层原则适用于 UART、SPI 和 MIPI；真正需要随设备类型改变的，是对上层呈现的语义与所选择的成熟子系统，而不是 VFS 的基本思想。
