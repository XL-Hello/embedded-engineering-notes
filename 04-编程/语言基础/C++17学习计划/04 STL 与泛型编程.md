# STL 与泛型编程

本文对应 [C++17 学习计划](../C++17学习计划.md)的第四阶段，承接 [现代 C++11 与 C++14 核心机制](现代%20C++11%20与%20C++14%20核心机制.md)。

本阶段要解决三个问题：怎样选择容器，怎样通过迭代器和算法处理数据，以及怎样把重复逻辑写成保留类型检查的模板。

文中的 `cpp` 代码使用 C++17；未注明“完整示例”的代码块是局部片段。时间复杂度描述操作规模增长的趋势，不直接等同于实际耗时或实时性保证。

## 一、容器选择与访问稳定性

### 1.1 容器怎么选

#### 1.1.1 数据规模、访问模式与资源成本

选容器之前，先回答：元素个数是否固定，是否需要连续内存，主要按下标还是按键访问，是否经常插入删除，以及地址是否必须稳定。

| 容器 | 组织方式与典型实现 | 常见复杂度 | 主要成本与用途 |
| --- | --- | --- | --- |
| `array<T,N>` | 对象内嵌的固定长度连续元素 | 下标 O(1) | 不为元素单独动态分配；长度属于类型 |
| `vector<T>` | 连续动态数组 | 下标 O(1)，尾插摊还 O(1)，中间插删 O(n) | 局部性好；扩容可能重新分配 |
| `deque<T>` | 常见为分段数组，整体不保证连续 | 下标与两端单元素插入 O(1) | 适合两端操作；有分段管理成本 |
| `list<T>` | 双向链表 | 已知位置插删 O(1)，查找 O(n) | 节点和指针开销大；随机访问差 |
| `map<K,V>`、`set<K>` | 有序结构，常见为平衡树 | 查找、普通单元素插入删除 O(log n) | 有序遍历；节点开销 |
| `unordered_map<K,V>`、`unordered_set<K>` | 哈希桶与元素存储 | 查找平均 O(1)，最坏 O(n) | 无排序保证；桶、装载因子与 rehash 成本 |
| `stack<T>`、`queue<T>` | 容器适配器，默认基于 `deque` | 取决于底层容器 | 限制为栈或队列接口，不提供通用遍历 |
| `string` | 连续字符序列，拥有内容 | 下标 O(1)，查找依接口而定 | 可增长；小字符串优化不是标准保证 |

红黑树、分段数组等属于常见实现，标准主要规定行为、复杂度和失效规则。不要由某个平台的节点大小推断所有平台的内存占用。

固定通道采样常适合 `array`；批量解析可变长数据常适合 `vector`；按设备 ID 查询可以考虑 `map` 或 `unordered_map`。少量设备也可能用线性数组更简单、更省内存，需要测量后再决定。

#### 1.1.2 字符串、键与隐式插入

```cpp
#include <map>
#include <string>

std::map<std::string, int> counters;
auto found = counters.find("uart");
if (found != counters.end()) {
    int count = found->second;
    (void)count;
}

counters["uart"] += 1;  // 不存在时插入一个初始值为 0 的 int
```

`operator[]` 适合需要“没有就创建”的场景，不能把它当成纯查询。`find()` 不插入，`at()` 在缺少键时抛出 `std::out_of_range`。禁用异常的项目应选择与错误策略一致的接口。

哈希容器的相等判定和哈希函数必须一致：相等的键必须得到相同哈希值。自定义比较器则必须满足严格弱序，不能随意用 `<=` 替代 `<`。

### 1.2 `vector`：容量与元素数量

```cpp
#include <vector>

std::vector<int> samples;
samples.reserve(128);  // 预留容量，不创建 128 个元素
samples.push_back(10);
samples.resize(4);     // size 变为 4，新增整数初始化为 0
```

`size()` 是已存在元素个数，`capacity()` 是当前分配能容纳的元素数量。`reserve()` 不改变 `size()`，因此不能在刚 `reserve(128)` 后访问 `samples[100]`。

尾插的“摊还 O(1)”不代表每次都耗时固定：某次扩容可能分配并搬迁全部元素。实时路径应提前约束最大容量，或采用真正的固定容量结构。不要在每次插入前都 `reserve(size()+1)`，这可能破坏几何增长带来的效率。

`emplace_back` 直接用参数构造元素，但不保证避免扩容，也不保证永远比 `push_back` 更快。

### 1.3 容器修改后的迭代器与引用失效

| 操作 | 需要记住的失效规则 |
| --- | --- |
| `vector` 扩容 | 指向元素的迭代器、指针和引用全部失效 |
| `vector` 不扩容的插入 | 插入点及其后的迭代器、指针和引用失效；旧 `end()` 也失效 |
| `vector::erase` | 删除位置及其后的迭代器和引用失效 |
| `list` 插入 | 通常不影响现有元素迭代器和引用；删除只影响被删元素 |
| `map/set` 插入 | 不使现有迭代器和引用失效；删除只影响被删元素 |
| 无序容器 rehash | 迭代器失效，但已有元素的引用和指针仍有效；被删除元素除外 |
| `deque` 两端插入 | 现有元素引用通常保持有效，迭代器失效；中间插入规则更严格 |

表格覆盖常见情形，不代替各成员函数的完整规则；`swap`、移动赋值、删除尾元素等还涉及边界和分配器条件。缓存下标也不一定解决问题：删除或插入后，同一下标可能已经代表另一个元素。

这些规则可对照 [C++17 草案的容器章节](https://timsong-cpp.github.io/cppwp/n4659/containers)，尤其要区分“迭代器失效”和“元素引用失效”。

## 二、迭代器与算法

### 2.1 迭代器与算法的使用契约

#### 2.1.1 半开区间与迭代器分类

标准算法常用 `[first, last)` 表示范围：包含起点，不包含终点。`end()` 指向尾后位置，不能解引用。

```cpp
#include <algorithm>
#include <iterator>
#include <vector>

std::vector<int> values{3, 1, 2};
auto found = std::find(std::begin(values), std::end(values), 2);
if (found != std::end(values)) {
    *found = 20;
}
```

| 类别 | 能力 | 常见例子 |
| --- | --- | --- |
| 输入迭代器 | 读取、单遍前进 | 输入流迭代器 |
| 输出迭代器 | 写入、单遍前进 | `back_inserter` |
| 前向迭代器 | 可多遍前进 | `forward_list` 迭代器 |
| 双向迭代器 | 可前进、后退 | `list`、有序关联容器迭代器 |
| 随机访问迭代器 | 支持位移和位置差 | `vector`、`array`、`deque` 迭代器 |

C++17 中不要把 C++20 的迭代器 concept 或 ranges 接口直接套进来。算法对迭代器有最低能力要求，例如 `std::sort` 需要随机访问迭代器，链表应使用自己的 `sort()`。

#### 2.1.2 `find`、`sort` 与 `transform`

```cpp
std::sort(values.begin(), values.end());

std::vector<int> scaled(values.size());
std::transform(values.begin(), values.end(), scaled.begin(),
               [](int value) { return value * 2; });
```

`transform` 不会自动扩大普通目标容器，目标范围必须能写入足够元素。另一种方式是使用 `std::back_inserter(scaled)` 让输出经 `push_back` 追加，这时不要预先 `resize` 出一批不需要的元素。

算法中的 Lambda 应满足算法契约，不要在比较器里修改容器结构。排序比较器需要严格弱序，并在排序过程中保持判定一致。

#### 2.1.3 `lower_bound` 的前提与成本

```cpp
std::vector<int> sorted{2, 4, 7, 9};
auto position = std::lower_bound(sorted.begin(), sorted.end(), 7);
const bool exists = position != sorted.end() && *position == 7;
```

它寻找第一个“不小于目标”的位置。范围需要按相应比较规则对目标形成正确分区；实践中通常先按相同比较规则排序。

比较次数为对数级，不代表所有迭代器上的移动次数也是对数级。在 `map/set` 上优先调用成员 `lower_bound()`，避免通用算法沿非随机访问迭代器大量步进。

### 2.2 `remove_if` 与 `erase`：逻辑范围和实际删除

```cpp
values.erase(
    std::remove_if(values.begin(), values.end(),
                   [](int value) { return value < 0; }),
    values.end());
```

`remove_if` 把保留元素移动到前部，返回逻辑新终点，不改变容器 `size()`。尾部元素仍存在，但内容不能当作原来的有效结果。`erase` 才真正缩短容器并销毁尾部对象。

对 `list` 可以使用成员 `remove_if`；`map` 的键不可修改，不能照搬这种移动覆盖的写法。C++17 中遍历关联容器删除元素，可以用 `it = container.erase(it)`，其他路径再递增。

## 三、模板与泛型约束

### 3.1 模板复用：参数、特化与转发

#### 3.1.1 函数模板与类模板

```cpp
#include <array>
#include <cstddef>

template<class T>
T larger(T left, T right) {
    return left < right ? right : left;
}

template<class T, std::size_t N>
struct SampleBlock {
    std::array<T, N> values{};
};

SampleBlock<int, 8> block;
```

模板参数可以是类型，也可以是编译期常量。`larger(1, 2)` 能推导 `T=int`，但 `larger(1, 2.0)` 不会自动推导出一个公共类型，两个参数的推导结果发生冲突。

模板定义通常放在头文件，让使用点能看到并实例化。也可以在明确控制类型集合时做显式实例化，但不能把任意模板定义移入 `.cpp` 后期待链接器自动生成所有版本。

#### 3.1.2 特化与偏特化

```cpp
template<class T>
struct IsPointer { static constexpr bool value = false; };

template<class T>
struct IsPointer<T*> { static constexpr bool value = true; };

template<>
struct IsPointer<void*> { static constexpr bool value = true; };
```

主模板给出通用形式，偏特化处理一组模式，全特化处理具体参数。函数模板可以全特化，但不能偏特化；函数场景经常优先用重载表达差异。

上例只说明机制，不是完整替代标准库的 `std::is_pointer`。工程中优先使用已经覆盖边界条件的标准类型萃取。

#### 3.1.3 可变参数模板与完美转发

```cpp
#include <memory>
#include <utility>

template<class T, class... Args>
std::unique_ptr<T> makeObject(Args&&... args) {
    return std::make_unique<T>(std::forward<Args>(args)...);
}
```

`Args...` 是参数包，`args...` 是函数参数包；末尾 `...` 按模式展开。这个工厂组合了转发引用和完美转发，保留实参的左右值类别。

参数包不是运行时数组。可以用 `sizeof...(Args)` 得到参数数量，C++17 还可通过折叠表达式归约参数包，下一阶段展开。

### 3.2 类型萃取与 SFINAE 的边界

#### 3.2.1 `type_traits` 与依赖类型

```cpp
#include <type_traits>

template<class T>
using Plain = std::remove_cv_t<std::remove_reference_t<T>>;

static_assert(std::is_same_v<Plain<const int&>, int>);
```

类型萃取提供类型属性判断与转换。这里组合去引用和去 cv 限定；不要使用 C++20 才提供的 `std::remove_cvref_t` 来冒充 C++17。

在模板中，依赖模板参数的嵌套类型往往需要 `typename`，例如 `typename T::value_type`，用于告诉编译器它是类型而不是数据成员。

#### 3.2.2 `enable_if`、SFINAE 与编译期分支

```cpp
template<class T,
         std::enable_if_t<std::is_integral_v<T>, int> = 0>
bool isEven(T value) {
    return value % 2 == 0;
}
```

条件为真时，`enable_if_t` 提供类型；为假时，相关替换失败可以让这个候选从重载集合中移除。这属于 SFINAE：替换失败不是错误。

SFINAE 主要作用于替换的直接上下文，并不意味着模板函数体中的任何错误都会被静默忽略。`isEven(1.5)` 没有适用候选时，整个调用仍然报错。

`if constexpr` 后来让一个模板内部的类型分支更直观，但它不等价于从重载集合中移除函数。选择接口是否可参与重载，与选择函数体里实例化哪条分支，是两个不同问题。

## 四、设备采样实践

### 4.1 设备采样：清洗、排序与查询

#### 4.1.1 完整示例

下面是可独立编译的 C++17 单文件示例：`g++ -std=c++17 -Wall -Wextra stl.cpp -o stl`。

```cpp
#include <algorithm>
#include <cassert>
#include <vector>

struct Sample {
    int channel;
    int value;
};

int main() {
    std::vector<Sample> samples{{2, 30}, {1, -1}, {3, 40}, {0, 20}};

    samples.erase(
        std::remove_if(samples.begin(), samples.end(),
                       [](const Sample& sample) { return sample.value < 0; }),
        samples.end());

    std::sort(samples.begin(), samples.end(),
              [](const Sample& left, const Sample& right) {
                  return left.channel < right.channel;
              });

    const int wanted = 2;
    auto found = std::lower_bound(
        samples.begin(), samples.end(), wanted,
        [](const Sample& sample, int channel) {
            return sample.channel < channel;
        });

    assert(samples.size() == 3);
    assert(found != samples.end());
    assert(found->channel == wanted);
    assert(found->value == 30);
    return 0;
}
```

先清理数据，再排序，最后查询，可以避免在结构变化时保存旧迭代器。示例假定通道不重复；若允许一个通道存在多个记录，需要定义取第一项、取最新项还是返回整个区间。

#### 4.1.2 练习与自查

| 练习 | 要做的事情 | 检查点 |
| --- | --- | --- |
| 容器选择 | 为固定采样块、设备注册表和发送队列选容器 | 能解释容量、顺序、分配和地址稳定性 |
| 扩容观察 | 记录 `vector` 的 size 和 capacity | 不依赖特定增长倍数，不使用失效指针 |
| 算法组合 | 清除非法值、排序并转换单位 | 明确输出容量与比较器前提 |
| 删除过程 | 分别观察 `remove_if` 后和 `erase` 后的 size | 能区分逻辑删除与实际删除 |
| 泛型封装 | 编写固定长度采样块模板 | 类型参数和长度参数含义清楚 |
| 模板约束 | 为整数运算添加 `enable_if` | 不把函数体错误误认为都会被 SFINAE 忽略 |

完成后，应能回答：

1. 为什么 `vector` 的摊还 O(1) 尾插不能直接满足硬实时要求？
2. `reserve()` 与 `resize()` 分别改变什么？
3. rehash 对无序容器的迭代器与引用有什么不同影响？
4. 为什么 `sort` 不能直接用于 `list`？为什么 map 查询优先使用成员函数？
5. `remove_if` 为什么还需要接一次 `erase`？
6. 模板定义为什么通常放在头文件？函数模板为什么不能偏特化？
7. SFINAE 与函数体内部的编译期分支分别解决什么问题？

下一阶段进入 [C++17 新特性](C++17%20新特性.md)，重点学习编译期分支、类型安全的数据表达和内存资源。
