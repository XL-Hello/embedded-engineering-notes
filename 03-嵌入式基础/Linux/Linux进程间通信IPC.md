# Linux 进程间通信 IPC

> 目标：理解 Linux 进程为什么需要 IPC，掌握管道、FIFO、消息队列、共享内存、信号量、信号和 Unix 域套接字的原理、常用接口、适用场景与避坑方法。
>
> 核心结论：**进程地址空间彼此隔离，IPC 的本质是借助内核提供的数据通道或共享区域，在进程之间传递数据、事件或同步状态。**

# 第一章、IPC 基础与核心概念

## 1.1 IPC 的定义

IPC（Inter-Process Communication，进程间通信）是不同进程之间交换数据和协调执行顺序的机制。

```text
进程 A 的独立地址空间
        |
        |  内核提供的 IPC 机制
        v
进程 B 的独立地址空间

数据传递：管道、FIFO、消息队列、Socket
共享数据：共享内存、mmap
事件通知：信号、eventfd
同步互斥：信号量、进程共享 mutex
```

线程通常共享同一进程的地址空间，可以直接访问全局变量和堆；进程地址空间相互隔离，不能直接解引用另一个进程中的普通指针。

# 第二章、Linux IPC 机制全景与选型

## 2.1 常见 IPC 方式对比

| IPC 方式 | 传递内容 | 是否适合无亲缘进程 | 主要特点 | 常见场景 |
| --- | --- | --- | --- | --- |
| 匿名管道 `pipe` | 字节流 | 否，通常用于亲缘进程 | 简单、单机、半双工 | 父子进程、Shell 管道 |
| 命名管道 `FIFO` | 字节流 | 是 | 文件系统中有名字 | 简单的本机进程通信 |
| 消息队列 | 有边界的消息 | 是 | 可按消息读取或分类 | 命令、事件、小块结构化数据 |
| 共享内存 | 共享内存区域 | 是 | 数据吞吐高，但必须同步 | 大块数据、高频交换 |
| 信号量 | 计数/同步状态 | 是 | 不负责传输业务数据 | 互斥、资源计数、执行同步 |
| 信号 `signal` | 信号编号 | 是 | 异步通知、信息量少 | 终止、重载、子进程状态通知 |
| Unix 域 Socket | 字节流或数据报 | 是 | 双向、接口统一、可传凭据 | 本机客户端/服务端 |
| 网络 Socket | 字节流或数据报 | 是 | 支持跨主机 | 分布式、网络服务 |

## 2.2 快速选型

```text
父子进程传少量字节流          -> pipe
无亲缘进程的简单字节流        -> FIFO
需要一条条接收命令/事件        -> 消息队列
大量、高频数据交换             -> 共享内存 + 同步机制
只通知“发生了某件事”          -> signal / eventfd
本机客户端—服务端、双向通信    -> Unix 域 Socket
需要跨主机                     -> TCP / UDP Socket
```

# 第三章、常用 IPC 机制原理与实践

## 3.1 匿名管道 pipe

### 3.1.1 原理

匿名管道是内核中的字节流缓冲区。`pipe()` 返回两个文件描述符：`fd[0]` 用于读，`fd[1]` 用于写。

```text
写进程                     内核管道                    读进程
write(fd[1])  ---------->  [字节流缓冲区]  ----------> read(fd[0])
```

```c
#include <unistd.h>

int pipe(int fd[2]);
```

匿名管道本身没有文件路径，通常在 `fork()` 前创建，让父子进程继承文件描述符。普通管道是单向的；需要双向通信时，应创建两条管道或改用 `socketpair()`。

### 3.1.2 父子进程示例

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

int main(void)
{
    int fd[2];
    pid_t pid;

    if (pipe(fd) == -1) {
        perror("pipe");
        return 1;
    }

    pid = fork();
    if (pid == -1) {
        perror("fork");
        return 1;
    }

    if (pid == 0) {
        char buf[64];
        ssize_t n;

        close(fd[1]);
        n = read(fd[0], buf, sizeof(buf) - 1);
        if (n > 0) {
            buf[n] = '\0';
            printf("child receive: %s\n", buf);
        }
        close(fd[0]);
        return 0;
    }

    close(fd[0]);
    write(fd[1], "hello", strlen("hello"));
    close(fd[1]);
    waitpid(pid, NULL, 0);
    return 0;
}
```

关键点：

- 父子进程必须关闭自己不用的管道端，否则可能导致读端一直等不到 EOF。
- 当所有写端都关闭后，读端读完剩余数据，`read()` 返回 `0`，表示 EOF。
- 没有任何读端时继续写管道，会产生 `SIGPIPE`，`write()` 通常返回 `EPIPE`。
- 管道是字节流，没有天然消息边界；接收方必须自行设计长度、分隔符或固定格式。
- 不超过 `PIPE_BUF` 的单次写入具有原子性；更大的写入可能与其他写进程的数据交错。

### 3.1.3 Shell 管道的本质

```bash
ps aux | grep app
```

Shell 创建管道和两个子进程，再通过 `dup2()` 把前一个进程的标准输出连接到管道写端，把后一个进程的标准输入连接到管道读端：

```text
ps 的 stdout -> pipe -> grep 的 stdin
```

## 3.2 命名管道 FIFO

FIFO 与匿名管道一样传输无边界字节流，但它在文件系统中有路径，因此无亲缘关系的进程也能通过路径打开同一条通道。

```c
#include <sys/stat.h>

int mkfifo(const char *pathname, mode_t mode);
```

命令行演示：

```bash
mkfifo /tmp/demo_fifo

# 终端 1：先阻塞等待数据
cat /tmp/demo_fifo

# 终端 2：写入数据
echo "hello fifo" > /tmp/demo_fifo

rm /tmp/demo_fifo
```

C 程序通过普通文件接口访问 FIFO：

```c
int fd = open("/tmp/demo_fifo", O_WRONLY);
write(fd, data, length);
close(fd);
```

注意事项：

- 只读方式打开 FIFO 时，默认等待写端；只写方式打开时，默认等待读端。
- `O_NONBLOCK` 会改变打开和读写行为，程序必须处理 `ENXIO`、`EAGAIN` 等返回值。
- FIFO 路径只是入口，实际数据仍经过内核缓冲区，不会写入磁盘文件内容。
- 多进程写同一 FIFO 时，同样应关注 `PIPE_BUF` 原子写入限制和应用层消息边界。

## 3.3 消息队列

消息队列由内核保存一组有边界的消息。与管道的连续字节流不同，接收方每次读取一条消息，不需要自己从字节流中拆包。

```text
发送进程 -> [消息 1][消息 2][消息 3] -> 接收进程
                  内核消息队列
```

Linux 常见两套接口：

| 类型 | 创建/打开 | 发送/接收 | 清理 |
| --- | --- | --- | --- |
| System V 消息队列 | `msgget` | `msgsnd`、`msgrcv` | `msgctl(..., IPC_RMID, ...)` |
| POSIX 消息队列 | `mq_open` | `mq_send`、`mq_receive` | `mq_close`、`mq_unlink` |

### 3.3.1 System V 消息队列

```c
#include <sys/ipc.h>
#include <sys/msg.h>

int msgget(key_t key, int msgflg);
int msgsnd(int msqid, const void *msgp, size_t msgsz, int msgflg);
ssize_t msgrcv(int msqid, void *msgp, size_t msgsz,
               long msgtyp, int msgflg);
int msgctl(int msqid, int cmd, struct msqid_ds *buf);
```

消息结构的第一个成员必须是类型为 `long` 的消息类型字段；发送时其值必须大于 `0`，可用作消息分类：

```c
struct message {
    long type;
    char text[128];
};
```

发送和接收示例：

```c
struct message msg = {1, "start"};

/* msgsz 不包含 long type */
msgsnd(msqid, &msg, sizeof(msg.text), 0);
msgrcv(msqid, &msg, sizeof(msg.text), 1, 0);
```

`msgrcv()` 的 `msgtyp` 可按类型选择消息：

| `msgtyp` | 含义 |
| ---: | --- |
| `0` | 读取队列中的第一条消息 |
| `> 0` | 读取指定类型的第一条消息 |
| `< 0` | 读取类型值不大于其绝对值的最小类型消息 |

System V IPC 对象通常不会因为创建进程退出就自动删除，应由明确的所有者调用 `IPC_RMID` 清理。

### 3.3.2 POSIX 消息队列

POSIX 消息队列使用类似文件名的名字，例如 `/app_cmd`，支持消息优先级和通知机制：

```c
mqd_t mq_open(const char *name, int oflag, ...);
int mq_send(mqd_t mqdes, const char *msg_ptr,
            size_t msg_len, unsigned int msg_prio);
ssize_t mq_receive(mqd_t mqdes, char *msg_ptr,
                   size_t msg_len, unsigned int *msg_prio);
```

消息队列适合命令、状态和小块结构化数据。若持续传输大块数据，频繁在用户态与内核之间复制会增加开销，通常考虑共享内存。

## 3.4 共享内存

共享内存把同一组物理内存页映射到多个进程的虚拟地址空间。建立映射后，进程可像访问普通内存一样读写数据，适合大块、高频数据交换。

```text
进程 A 虚拟地址             共享物理内存             进程 B 虚拟地址
0x7f... ───────────────> [共享数据区域] <────────────── 0x7a...

两个进程中的虚拟地址可以不同，指向的共享内存页相同。
```

Linux 常见两套共享内存接口：

| 类型 | 创建/获取 | 映射 | 解除/删除 |
| --- | --- | --- | --- |
| System V | `shmget` | `shmat` | `shmdt`、`shmctl(IPC_RMID)` |
| POSIX | `shm_open` + `ftruncate` | `mmap` | `munmap`、`shm_unlink` |

### 3.4.1 POSIX 共享内存基本流程

创建方：

```c
int fd = shm_open("/demo_shm", O_CREAT | O_RDWR, 0600);
ftruncate(fd, sizeof(struct shared_data));

struct shared_data *p = mmap(NULL, sizeof(*p),
                             PROT_READ | PROT_WRITE,
                             MAP_SHARED, fd, 0);
close(fd);
```

使用方打开同名对象并映射：

```c
int fd = shm_open("/demo_shm", O_RDWR, 0);

struct shared_data *p = mmap(NULL, sizeof(*p),
                             PROT_READ | PROT_WRITE,
                             MAP_SHARED, fd, 0);
close(fd);
```

结束时：

```c
munmap(p, sizeof(*p));
shm_unlink("/demo_shm");  /* 由对象所有者执行一次 */
```

`shm_unlink()` 删除名字；已经建立的映射仍可使用，直到相关进程 `munmap()` 或退出。

### 3.4.2 共享内存为什么快

管道、消息队列和 Socket 通常需要通过内核缓冲区传递数据：

```text
发送进程用户空间 -> 内核缓冲区 -> 接收进程用户空间
```

共享内存建立映射后，双方直接访问同一内存区域，避免每次消息传递都复制整块业务数据：

```text
进程 A ──读写──> 同一共享内存页 <──读写── 进程 B
```

但共享内存只解决“数据放在哪里”，不解决“谁先读写”。没有同步机制时，同样会发生数据竞争、读到半更新数据或覆盖未消费数据。

## 3.5 信号量：进程间同步

信号量本质是一个受内核或原子机制管理的计数器：

- `wait/P`：计数大于 `0` 时减 `1`；否则阻塞。
- `post/V`：计数加 `1`，并唤醒等待者。

```text
生产者：写共享内存 -> post(data_ready)
消费者：wait(data_ready) -> 读共享内存
```

信号量负责同步和资源计数，不负责传输业务数据。常与共享内存配合：共享内存存数据，信号量保护互斥并通知数据是否可用。

### 3.5.1 POSIX 信号量

```c
#include <semaphore.h>

int sem_wait(sem_t *sem);
int sem_trywait(sem_t *sem);
int sem_post(sem_t *sem);
```

两种形式：

| 形式 | 初始化方式 | 适用场景 |
| --- | --- | --- |
| 命名信号量 | `sem_open` | 无亲缘进程通过名字访问 |
| 无名信号量 | `sem_init` | 放在共享内存中供多个进程访问 |

无名信号量用于进程间共享时，必须把它本身放入共享内存，并设置 `pshared` 为非 `0`：

```c
sem_init(&shared->sem, 1, 0);
```

### 3.5.2 进程共享 mutex

互斥锁也可以放在共享内存中，并通过属性设置为进程共享：

```c
pthread_mutexattr_t attr;

pthread_mutexattr_init(&attr);
pthread_mutexattr_setpshared(&attr, PTHREAD_PROCESS_SHARED);
pthread_mutex_init(&shared->mutex, &attr);
pthread_mutexattr_destroy(&attr);
```

如果持锁进程可能异常退出，可研究 robust mutex；否则锁的共享状态可能永久停留在“已占用”。

## 3.6 信号 signal

信号是内核发送给进程或线程的异步事件通知，适合表达“发生了某件事”，不适合传输大量数据。

常见信号：

| 信号 | 常见来源或含义 |
| --- | --- |
| `SIGINT` | 终端按下 `Ctrl+C` |
| `SIGTERM` | 请求进程正常终止 |
| `SIGKILL` | 强制终止，不能捕获、阻塞或忽略 |
| `SIGCHLD` | 子进程停止或退出 |
| `SIGHUP` | 常用于通知守护进程重新加载配置 |
| `SIGPIPE` | 向没有读端的管道或 Socket 写数据 |

推荐使用 `sigaction()` 注册处理函数：

```c
#include <signal.h>

static volatile sig_atomic_t stop;

static void on_signal(int signo)
{
    (void)signo;
    stop = 1;
}

int main(void)
{
    struct sigaction sa = {0};

    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);

    while (!stop) {
        /* 正常工作 */
    }

    return 0;
}
```

信号处理函数会打断正常执行流，只能调用异步信号安全函数。不要在处理函数中调用 `printf()`、`malloc()`、获取普通互斥锁或执行复杂业务逻辑。常见做法是只设置 `sig_atomic_t` 标志，或在处理函数中对预先创建且已设为非阻塞的 self-pipe/eventfd 文件描述符调用 `write()` 写入通知，再由主循环处理；若返回 `EAGAIN`，可合并或丢弃本次通知，由主循环统一处理。

标准信号通常不会记录重复到达次数；同一种信号阻塞期间多次到达，可能只保留一个待处理状态。需要排队和携带少量值时，可了解 POSIX 实时信号，但仍不应把信号当作常规数据通道。

## 3.7 Unix 域 Socket

Unix 域 Socket 使用 Socket 编程接口在同一台主机的进程间双向通信，不经过 IP 网络协议栈，常用于本机客户端—服务端。

```text
客户端进程 <========== 双向通信 ==========> 服务端进程
     connect()       Unix 域 Socket          bind()/listen()/accept()
```

地址族使用 `AF_UNIX` 或 `AF_LOCAL`：

```c
struct sockaddr_un addr = {0};

addr.sun_family = AF_UNIX;
strncpy(addr.sun_path, "/tmp/app.sock",
        sizeof(addr.sun_path) - 1);
```

常见类型：

| 类型 | 特点 |
| --- | --- |
| `SOCK_STREAM` | 面向连接、可靠字节流，无消息边界 |
| `SOCK_DGRAM` | 数据报，有消息边界 |
| `SOCK_SEQPACKET` | 面向连接、可靠并保留消息边界 |

服务端流程：

```text
socket -> unlink 旧路径 -> bind -> listen -> accept -> read/write -> close
```

客户端流程：

```text
socket -> connect -> read/write -> close
```

与 FIFO 相比，Unix 域 Socket 天然支持全双工、多个客户端和更清晰的连接管理；在 Linux 上还可传递文件描述符和获取对端凭据。使用文件系统路径时，服务端退出前后应妥善清理旧的 Socket 文件，并设置合适的目录与文件权限。

### 3.7.1 socketpair

`socketpair()` 创建一对已连接的本地 Socket，适合亲缘进程双向通信：

```c
int fd[2];
socketpair(AF_UNIX, SOCK_STREAM, 0, fd);
```

与两条单向管道相比，`socketpair()` 天然全双工，常用于父子进程控制通道。

## 3.8 其他常见机制

### 3.8.1 mmap 文件映射

多个进程用 `mmap(..., MAP_SHARED, ...)` 映射同一个普通文件，也可以共享数据并持久化到文件。它与 POSIX 共享内存的映射方式相似，但底层对象是实际文件。

### 3.8.2 eventfd

`eventfd` 是 Linux 提供的 64 位计数通知机制，可被 `select`、`poll`、`epoll` 监听。它适合线程或亲缘进程之间进行事件计数和唤醒，但通常不传输业务数据。

### 3.8.3 文件锁

`flock()` 或 `fcntl()` 记录锁可用于协调多个进程对同一文件的访问。多数文件锁是协作式锁：所有参与进程都必须主动遵守加锁规则。

## 3.9 阻塞、非阻塞与 I/O 多路复用

管道、FIFO 和 Socket 的读写通常支持阻塞或非阻塞模式；POSIX 消息队列可在 `mq_open()` 时使用 `O_NONBLOCK`，System V 消息队列则在 `msgsnd()` 或 `msgrcv()` 的调用标志中使用 `IPC_NOWAIT`：

| 模式 | 行为 |
| --- | --- |
| 阻塞 | 暂时无法读写时让调用线程休眠等待 |
| 非阻塞 | 暂时无法读写时立即返回；非阻塞 fd 和 POSIX 消息队列常见 `EAGAIN/EWOULDBLOCK`，System V 消息队列空读返回 `ENOMSG`、满写返回 `EAGAIN` |

当一个进程需要同时管理多个管道或 Socket 时，可使用 `select`、`poll` 或 `epoll` 等待多个文件描述符事件，避免为每条连接单独创建一个阻塞线程。

并非所有 IPC 都能直接作为文件描述符交给 `epoll`。普通管道、FIFO、Socket、eventfd 可以；System V 消息队列和 System V 信号量不能直接这样监听。

# 第四章、工程应用、排查与可靠性设计

## 4.1 典型应用场景与选型

| 应用场景 | 推荐 IPC | 原因与注意点 |
| --- | --- | --- |
| Shell 或父子进程单向传递输出 | 匿名管道 `pipe` | 通过 `fork()` 继承描述符；使用完及时关闭无用端。 |
| 两个独立本机进程传递简单字节流 | FIFO | 可通过路径发现对方；仍需定义消息边界。 |
| 分发离散命令、任务或事件 | 消息队列 | 天然保留消息边界；适合小块结构化消息。 |
| 图像、音频、传感器等大块高频数据 | 共享内存 + 信号量/mutex | 减少数据复制；必须设计同步、缓冲区和异常恢复。 |
| 只通知状态变化或退出 | 信号 / `eventfd` | 信号只做轻量通知；需要接入事件循环时优先考虑 `eventfd`。 |
| 本机多客户端服务、需要双向请求响应 | Unix 域 Socket | 支持全双工、连接管理、权限与对端凭据。 |
| 跨主机服务通信 | TCP / UDP Socket | 需要处理网络断连、超时、协议与安全问题。 |

## 4.2 生命周期与清理

不同 IPC 对象的清理方式不同：

| 对象 | 何时消失或如何清理 |
| --- | --- |
| 匿名管道 | 所有相关文件描述符关闭后消失 |
| FIFO | 数据通道关闭，但路径需 `unlink()` 删除 |
| System V 消息队列 | `msgctl(..., IPC_RMID, ...)` |
| System V 共享内存 | `shmctl(..., IPC_RMID, ...)`，最后一次分离后释放 |
| POSIX 消息队列 | `mq_unlink()` 删除名字 |
| POSIX 共享内存 | `shm_unlink()` 删除名字 |
| POSIX 命名信号量 | `sem_unlink()` 删除名字 |
| Unix 域 Socket 路径 | 服务端 `unlink()` 删除路径 |

设计 IPC 时应明确“谁创建、谁初始化、谁删除”。多个进程都随意初始化或删除对象，容易造成竞态、数据丢失和重启失败。

## 4.3 查看与排查 IPC

### 4.3.1 System V IPC

```bash
ipcs -q        # 消息队列
ipcs -m        # 共享内存
ipcs -s        # 信号量
ipcs -a        # 全部 System V IPC

ipcrm -q <msqid>
ipcrm -m <shmid>
ipcrm -s <semid>
```

### 4.3.2 文件描述符与 Unix 域 Socket

```bash
ls -l /proc/<pid>/fd
lsof -p <pid>
ss -xl          # Unix 域监听 Socket
ss -xa          # 全部 Unix 域 Socket
```

### 4.3.3 系统调用跟踪

```bash
strace -f -e trace=%process,%ipc,%signal,%desc ./app
```

`-f` 跟踪子进程；可观察 `fork`、`pipe`、`read/write`、System V IPC 和信号相关调用。排查阻塞问题时，重点确认进程卡在哪个系统调用、哪些文件描述符没有关闭、IPC 对象是否仍存在。

## 4.4 常见问题与避坑

### 4.4.1 把字节流当成完整消息

`read()` 一次不保证正好读取一次 `write()` 的全部数据。管道、FIFO 和 `SOCK_STREAM` 都必须设计应用层协议，例如固定长度、分隔符或“长度头 + 数据体”。

```text
[4 字节长度 N][N 字节数据][4 字节长度 M][M 字节数据]...
```

### 4.4.2 忽略短读和短写

`read()`、`write()`、`send()`、`recv()` 的返回值可能小于请求长度，也可能被信号中断并返回 `EINTR`。可靠程序需要循环处理剩余数据，并区分 EOF、可重试错误和永久错误。

### 4.4.3 忘记关闭无用文件描述符

`fork()` 会复制文件描述符表。父子进程必须关闭自己不用的管道端或 Socket 端，否则 EOF、资源释放和故障检测都可能延迟。

### 4.4.4 共享内存没有同步

共享内存不是“自动线程安全”。应明确数据所有权、读写顺序、内存可见性和异常恢复方式，并使用信号量、进程共享 mutex 或无锁协议同步。

### 4.4.5 IPC 对象残留

System V IPC、POSIX 命名对象、FIFO 和 Unix 域 Socket 路径都可能在异常退出后残留。程序启动和退出流程都要考虑检查、复用或清理旧对象。

### 4.4.6 权限设置过宽

FIFO、Socket 路径和命名 IPC 对象都可能成为进程间的数据入口。应使用最小权限，校验对端身份和输入长度，不要为了方便直接使用 `0666` 或对所有用户开放。

### 4.4.7 信号处理函数做复杂工作

处理函数中只执行异步信号安全操作。复杂清理、日志输出和状态变更应转移到正常执行流处理。

# 第五章、核心知识速览与面试要点

## 5.1 核心接口速查

| 使用场景 | 核心接口 |
| --- | --- |
| 创建匿名管道 | `pipe` |
| 创建命名管道 | `mkfifo` |
| System V 消息队列 | `msgget`、`msgsnd`、`msgrcv`、`msgctl` |
| POSIX 消息队列 | `mq_open`、`mq_send`、`mq_receive`、`mq_unlink` |
| System V 共享内存 | `shmget`、`shmat`、`shmdt`、`shmctl` |
| POSIX 共享内存 | `shm_open`、`ftruncate`、`mmap`、`shm_unlink` |
| POSIX 信号量 | `sem_init/sem_open`、`sem_wait`、`sem_post` |
| 注册信号处理 | `sigaction` |
| Unix 域 Socket | `socket`、`bind`、`listen`、`accept`、`connect` |
| 父子进程双向通道 | `socketpair` |
| 等待多个 fd | `select`、`poll`、`epoll` |

## 5.2 高频面试题

### 5.2.1 进程和线程通信有什么区别

同一进程的线程共享地址空间，可直接访问全局变量和堆，但必须解决并发同步；不同进程地址空间隔离，需要通过内核 IPC 或共享映射交换数据，隔离性更强，通信方式也更明确。

### 5.2.2 管道和消息队列有什么区别

管道是连续字节流，没有消息边界，通常按读写顺序消费；消息队列保留消息边界，还可按消息类型或优先级接收。管道简单，消息队列更适合传递离散命令和事件。

### 5.2.3 为什么共享内存通常最快

映射建立后，多个进程直接访问同一组物理内存页，不必让每块业务数据反复经过“发送方用户态—内核缓冲区—接收方用户态”的复制路径。但它必须额外解决同步、数据一致性和异常恢复。

### 5.2.4 共享内存和信号量如何配合

共享内存存放业务数据，信号量负责互斥、资源计数或就绪通知。例如生产者写完数据后 `post`，消费者 `wait` 成功后读取；多槽缓冲区常使用“空槽计数 + 数据计数 + 互斥锁”。

### 5.2.5 pipe 和 FIFO 有什么区别

两者都是内核字节流管道。匿名管道没有路径，通常依靠 `fork()` 继承描述符，适合亲缘进程；FIFO 在文件系统中有名字，无亲缘进程也能通过相同路径打开。

### 5.2.6 signal 能否用于传输数据

普通信号主要传递信号编号，只适合异步事件通知；标准信号还可能合并，不能可靠记录重复次数。少量附加值可用实时信号，但常规数据应选择管道、消息队列、共享内存或 Socket。

### 5.2.7 Unix 域 Socket 和网络 Socket 的区别

两者编程模型相似。Unix 域 Socket 只在本机使用，通过路径或抽象地址标识端点，通常开销更低，还支持传递文件描述符和对端凭据；网络 Socket 可跨主机通信。

## 5.3 快速记忆

```text
字节流：pipe、FIFO、SOCK_STREAM
消息：消息队列、SOCK_DGRAM、SOCK_SEQPACKET
大数据：共享内存 + 信号量/mutex
通知：signal、eventfd
本机服务：Unix 域 Socket
跨主机：TCP / UDP Socket

管道和流式 Socket 没有消息边界
共享内存速度快，但必须自己同步
信号适合通知，不适合传输业务数据
IPC 对象必须明确创建者、所有者和清理者
```
