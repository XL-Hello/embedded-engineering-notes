# Linux pthread 多线程基础

> 目标：掌握 Linux C 开发中最常用的 pthread 接口，理解线程生命周期、共享资源竞争、互斥锁和条件变量，并能完成常见的线程创建与生产者—消费者模型。
>
> 核心结论：**线程共享进程的地址空间，创建和切换开销通常小于进程，但共享数据必须通过互斥与同步机制保护。**

## 1. 一句话理解 pthread

`pthread` 是 POSIX 线程接口。一个进程可以包含多个线程；线程拥有各自的栈和执行流，但共享进程内的全局变量、静态变量、堆、文件描述符等资源。

```text
进程
├── 线程 1：独立栈、寄存器、执行流
├── 线程 2：独立栈、寄存器、执行流
└── 共享资源：全局/静态变量、堆、文件描述符、进程地址空间
```

多线程适合并发 I/O、后台任务和可拆分的并行计算。它的核心风险是多个线程同时读写共享资源，产生数据竞争、状态错乱甚至崩溃。

编译 pthread 程序时使用 `-pthread`：

```bash
gcc -Wall -Wextra -pthread demo.c -o demo
```

`-pthread` 不只是链接选项，还会启用与线程相关的编译配置，因此通常优先于只写 `-lpthread`。

## 2. 线程创建与参数传递

### 2.1 pthread_create

```c
int pthread_create(pthread_t *thread,
                   const pthread_attr_t *attr,
                   void *(*start_routine)(void *),
                   void *arg);
```

| 参数 | 作用 |
| --- | --- |
| `thread` | 输出新线程 ID |
| `attr` | 线程属性；传 `NULL` 使用默认属性 |
| `start_routine` | 线程入口函数 |
| `arg` | 传给入口函数的参数 |

返回 `0` 表示成功，非 `0` 表示错误码。pthread 接口通常直接返回错误码，不一定设置 `errno`。

### 2.2 基础示例

```c
#include <pthread.h>
#include <stdio.h>
#include <string.h>

struct thread_arg {
    int id;
    const char *name;
};

static void *worker(void *arg)
{
    struct thread_arg *ctx = arg;
    printf("worker: id=%d, name=%s\n", ctx->id, ctx->name);
    return NULL;
}

int main(void)
{
    pthread_t tid;
    struct thread_arg arg = {1, "read_task"};
    int ret;

    ret = pthread_create(&tid, NULL, worker, &arg);
    if (ret != 0) {
        fprintf(stderr, "pthread_create: %s\n", strerror(ret));
        return 1;
    }

    ret = pthread_join(tid, NULL);
    if (ret != 0) {
        fprintf(stderr, "pthread_join: %s\n", strerror(ret));
        return 1;
    }

    return 0;
}
```

传参时必须保证参数在线程使用期间仍然有效。不要把循环中不断变化的同一个局部变量地址直接交给多个线程，也不要在线程尚未读取前让局部变量离开作用域。

## 3. 线程生命周期

### 3.1 pthread_join：等待并回收

```c
int pthread_join(pthread_t thread, void **retval);
```

`pthread_join()` 阻塞等待指定线程结束，回收其线程资源，并可通过 `retval` 接收返回值。一个可连接线程最终应由其他线程 `join`，否则退出后仍会保留部分资源。

### 3.2 pthread_detach：退出后自动回收

```c
int pthread_detach(pthread_t thread);
```

分离线程结束后由系统自动回收，不能再对它调用 `pthread_join()`。适合不需要等待结果的后台任务，但进程退出仍会终止其中的所有线程。

```c
pthread_t tid;

if (pthread_create(&tid, NULL, worker, NULL) == 0)
    pthread_detach(tid);
```

也可以在创建时通过线程属性设置分离态；相比“先创建、再 detach”，创建即分离更容易统一错误处理。

### 3.3 pthread_exit 与 return

```c
void pthread_exit(void *retval);
```

在线程入口函数中，`return value` 与 `pthread_exit(value)` 都会结束当前线程。区别在主线程：

- `main()` 执行 `return` 或调用 `exit()`：结束整个进程，其他线程也随之终止。
- 主线程调用 `pthread_exit(NULL)`：只结束主线程，进程可继续等待其他线程运行。

线程返回指针时，不能返回线程栈上局部变量的地址；可返回堆内存地址，并由 `join` 方负责释放。

### 3.4 线程 ID

```c
pthread_t pthread_self(void);
int pthread_equal(pthread_t t1, pthread_t t2);
```

`pthread_t` 是不透明类型。比较两个线程 ID 应使用 `pthread_equal()`，不要假设它一定是整数并直接使用 `==`。

## 4. 数据竞争与互斥锁

### 4.1 为什么需要互斥锁

`cnt++` 通常包含“读取、计算、写回”多个步骤。两个线程交叉执行时，可能读取到相同旧值，导致一次累加丢失。

```text
线程 A：读取 cnt=10 ── 加 1 ── 写回 11
线程 B：读取 cnt=10 ── 加 1 ── 写回 11
预期结果：12；实际结果：11
```

互斥锁保证同一时刻只有一个线程进入临界区：

```c
pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;

pthread_mutex_lock(&mutex);
/* 访问共享资源 */
pthread_mutex_unlock(&mutex);
```

### 4.2 常用接口

```c
int pthread_mutex_init(pthread_mutex_t *mutex,
                       const pthread_mutexattr_t *attr);
int pthread_mutex_lock(pthread_mutex_t *mutex);
int pthread_mutex_trylock(pthread_mutex_t *mutex);
int pthread_mutex_unlock(pthread_mutex_t *mutex);
int pthread_mutex_destroy(pthread_mutex_t *mutex);
```

| 接口 | 作用 |
| --- | --- |
| `pthread_mutex_lock` | 获取锁；锁被占用时阻塞 |
| `pthread_mutex_trylock` | 尝试获取锁；锁被占用时立即返回 |
| `pthread_mutex_unlock` | 释放当前线程持有的锁 |
| `pthread_mutex_destroy` | 锁不再使用时销毁 |

静态初始化适合全局或静态互斥锁；动态初始化适合需要配置属性或控制生命周期的对象。销毁前必须确保没有线程正在持有或等待该锁。

### 4.3 计数示例

```c
#include <pthread.h>
#include <stdio.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static int count;

static void *add(void *arg)
{
    (void)arg;

    for (int i = 0; i < 10000; ++i) {
        pthread_mutex_lock(&mutex);
        ++count;
        pthread_mutex_unlock(&mutex);
    }

    return NULL;
}

int main(void)
{
    pthread_t t1, t2;

    pthread_create(&t1, NULL, add, NULL);
    pthread_create(&t2, NULL, add, NULL);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);

    printf("count=%d\n", count);  /* 20000 */
    pthread_mutex_destroy(&mutex);
    return 0;
}
```

锁内只放必须保护的共享数据操作，避免在持锁期间执行长耗时计算、阻塞 I/O 或 `sleep()`。

## 5. 条件变量：等待与通知

条件变量用于等待“某个状态成立”，必须与互斥锁和共享状态一起使用。典型场景包括生产者—消费者、任务队列、资源就绪通知。

```c
pthread_cond_t cond = PTHREAD_COND_INITIALIZER;

int pthread_cond_wait(pthread_cond_t *cond, pthread_mutex_t *mutex);
int pthread_cond_signal(pthread_cond_t *cond);
int pthread_cond_broadcast(pthread_cond_t *cond);
int pthread_cond_destroy(pthread_cond_t *cond);
```

`pthread_cond_wait()` 会原子地释放互斥锁并进入等待；被唤醒后，它会先重新获得互斥锁，再返回调用方。

标准等待模板：

```c
pthread_mutex_lock(&mutex);

while (!condition_is_true())
    pthread_cond_wait(&cond, &mutex);

/* 条件已成立，安全访问共享状态 */
pthread_mutex_unlock(&mutex);
```

必须使用 `while` 重新检查条件，不能只用 `if`，原因包括虚假唤醒、多个消费者竞争，以及从收到通知到重新获得锁之间状态可能再次变化。

| 接口 | 唤醒范围 | 常见场景 |
| --- | --- | --- |
| `pthread_cond_signal` | 至少唤醒一个等待线程 | 一份资源只需一个线程处理 |
| `pthread_cond_broadcast` | 唤醒所有等待线程 | 全局状态变化，多个线程都需重新判断 |

条件变量本身不保存“通知次数”。真正表示状态的是受互斥锁保护的变量或队列；通知只是提醒等待线程重新检查状态。

## 6. 生产者—消费者完整示例

下面用单槽缓冲区演示正确的等待、通知和结束条件：

```c
#include <pthread.h>
#include <stdio.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t can_produce = PTHREAD_COND_INITIALIZER;
static pthread_cond_t can_consume = PTHREAD_COND_INITIALIZER;

static int value;
static int has_value;
static int finished;

static void *producer(void *arg)
{
    (void)arg;

    for (int i = 1; i <= 3; ++i) {
        pthread_mutex_lock(&mutex);

        while (has_value)
            pthread_cond_wait(&can_produce, &mutex);

        value = i;
        has_value = 1;
        printf("produce: %d\n", value);

        pthread_cond_signal(&can_consume);
        pthread_mutex_unlock(&mutex);
    }

    pthread_mutex_lock(&mutex);
    while (has_value)
        pthread_cond_wait(&can_produce, &mutex);
    finished = 1;
    pthread_cond_signal(&can_consume);
    pthread_mutex_unlock(&mutex);

    return NULL;
}

static void *consumer(void *arg)
{
    (void)arg;

    for (;;) {
        pthread_mutex_lock(&mutex);

        while (!has_value && !finished)
            pthread_cond_wait(&can_consume, &mutex);

        if (!has_value && finished) {
            pthread_mutex_unlock(&mutex);
            break;
        }

        printf("consume: %d\n", value);
        has_value = 0;
        pthread_cond_signal(&can_produce);
        pthread_mutex_unlock(&mutex);
    }

    return NULL;
}

int main(void)
{
    pthread_t producer_tid, consumer_tid;

    pthread_create(&producer_tid, NULL, producer, NULL);
    pthread_create(&consumer_tid, NULL, consumer, NULL);
    pthread_join(producer_tid, NULL);
    pthread_join(consumer_tid, NULL);

    pthread_cond_destroy(&can_produce);
    pthread_cond_destroy(&can_consume);
    pthread_mutex_destroy(&mutex);
    return 0;
}
```

数据流如下：

```text
生产者：等待空槽 -> 写入数据 -> 通知消费者
                         |
                         v
消费者：等待数据 <- 读取数据 <- 唤醒
           |
           └── 清空槽位并通知生产者
```

真实项目通常把单槽替换为环形队列：生产者等待“队列非满”，消费者等待“队列非空”，退出时再增加停止标志。

## 7. 常见问题与避坑

### 7.1 忘记 join 或 detach

可连接线程退出后仍需 `pthread_join()` 回收；如果不需要结果，应设置为分离线程。一个线程不能既 `join` 又 `detach`。

### 7.2 参数生命周期失效

线程参数指针必须在线程读取期间有效。批量创建线程时，可为每个线程准备独立参数对象，或分配堆内存并明确释放责任。

### 7.3 锁顺序不一致导致死锁

多个线程同时获取多把锁时，应统一加锁顺序：

```text
统一：先锁 A，再锁 B
禁止：线程 1 锁 A 等 B；线程 2 锁 B 等 A
```

### 7.4 持锁时间过长

先准备线程私有数据，再进入临界区快速更新共享状态。不要把网络读写、磁盘 I/O、长计算或休眠放在锁内。

### 7.5 把 volatile 当成线程同步

`volatile` 不能保证复合操作的原子性，也不能替代互斥锁或 C11 原子操作。共享变量存在并发读写时，必须使用正确的同步机制。

### 7.6 条件变量只通知、不记录状态

先在锁内修改共享状态，再调用 `signal` 或 `broadcast`。等待方始终在锁内用 `while` 检查状态，不能假设“收到一次通知就一定有一份资源”。

## 8. 核心接口速查

| 使用场景 | 核心接口 |
| --- | --- |
| 创建线程 | `pthread_create` |
| 等待线程结束并回收 | `pthread_join` |
| 线程退出后自动回收 | `pthread_detach` |
| 当前线程主动退出 | `pthread_exit` 或入口函数 `return` |
| 获取、比较线程 ID | `pthread_self`、`pthread_equal` |
| 保护共享资源 | `pthread_mutex_lock`、`pthread_mutex_unlock` |
| 非阻塞尝试加锁 | `pthread_mutex_trylock` |
| 等待状态成立 | `pthread_cond_wait` + `while` 条件判断 |
| 唤醒一个/全部等待线程 | `pthread_cond_signal`、`pthread_cond_broadcast` |

## 9. 面试速记

### 9.1 线程和进程的主要区别

进程拥有独立地址空间，隔离性更强；同一进程内的线程共享地址空间和大部分进程资源，但各自拥有栈、寄存器和执行流。线程通信方便、开销通常更小，但共享数据容易产生竞争。

### 9.2 mutex 和 condition variable 的区别

互斥锁解决“同一时刻谁能访问共享资源”；条件变量解决“条件不成立时如何休眠等待，条件变化后如何被唤醒”。条件变量必须与互斥锁和共享状态配合使用。

### 9.3 为什么 pthread_cond_wait 必须放在 while 中

线程可能虚假唤醒；多个等待线程被唤醒后还会竞争同一资源；重新获得互斥锁前，共享状态也可能被其他线程改变。因此返回后必须再次检查条件。

### 9.4 join 和 detach 如何选择

需要等待完成、获取结果或明确管理生命周期时使用 `join`；完全不关心返回值且希望线程自行回收时使用 `detach`。二者只能选择一种。

## 10. 快速记忆

```text
创建：pthread_create
回收：join 等待回收；detach 自动回收
互斥：mutex 保护共享资源
同步：condition variable 等待状态变化
原则：共享状态在锁内修改，等待条件用 while 检查
编译：gcc ... -pthread
```
