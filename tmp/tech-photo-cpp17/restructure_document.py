from pathlib import Path
from collections import Counter
import re

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'04-编程/语言基础/C++17学习计划/现代 C++11 与 C++14 核心机制.md'
SNAPSHOT=Path(__file__).parent/'modern-cpp-before-restructure.md'
original=DOC.read_bytes()
if SNAPSHOT.exists():
    raise RuntimeError('Snapshot already exists; do not overwrite this run baseline')
SNAPSHOT.write_bytes(original)
before=original.decode('utf-8')
changes={
'## 一、移动语义：区分复制数据与转移资源':'## 一、资源转移与泛型传参',
'### 1.1 左值、纯右值与将亡值':'### 1.1 值类别与 `std::move`\n\n#### 1.1.1 左值、纯右值与将亡值',
'### 1.2 左值引用与右值引用':'#### 1.1.2 左值引用与右值引用',
'### 1.3 `std::move` 是转换，不执行搬运':'#### 1.1.3 `std::move` 是转换，不执行搬运',
'### 1.4 移动构造与移动赋值':'### 1.2 资源转移与返回对象\n\n#### 1.2.1 移动构造与移动赋值',
'### 1.5 拷贝消除：直接构造结果':'#### 1.2.2 拷贝消除：直接构造结果',
'## 二、转发引用与泛型参数传递':'### 1.3 转发引用与完美转发',
'### 2.1 `T&&` 不一定是转发引用':'#### 1.3.1 `T&&` 不一定是转发引用',
'### 2.2 引用折叠与 `std::forward`':'#### 1.3.2 引用折叠与 `std::forward`',
'## 三、智能指针：把所有权写进类型':'## 二、所有权与回调',
'### 3.1 `unique_ptr`：单一所有者':'### 2.1 独占所有权与 C 资源管理\n\n#### 2.1.1 `unique_ptr`：单一所有者',
'### 3.2 自定义删除器：适配 C 资源':'#### 2.1.2 自定义删除器：适配 C 资源',
'### 3.3 `shared_ptr`：确实需要共享时再使用':'### 2.2 共享所有权与弱引用\n\n#### 2.2.1 `shared_ptr`：确实需要共享时再使用',
'### 3.4 `weak_ptr` 与循环引用':'#### 2.2.2 `weak_ptr` 与循环引用',
'### 3.5 工厂与内存成本':'#### 2.2.3 工厂与内存成本',
'## 四、Lambda：把行为与上下文放在一起':'### 2.3 Lambda 与回调生命周期',
'### 4.1 语法、捕获与 `mutable`':'#### 2.3.1 语法、捕获与 `mutable`',
'### 4.2 泛型 Lambda 与函数指针':'#### 2.3.2 泛型 Lambda 与函数指针',
'### 4.3 `std::function` 与 `std::bind`':'#### 2.3.3 `std::function` 与 `std::bind`',
'## 五、其他常用语言工具':'## 三、语言工具与综合实践\n\n### 3.1 常用语言工具与易错点',
'### 5.1 范围 `for`、强类型枚举与别名':'#### 3.1.1 范围 `for`、强类型枚举与别名',
'### 5.2 `initializer_list`、`=default` 与 `=delete`':'#### 3.1.2 `initializer_list`、`=default` 与 `=delete`',
'### 5.3 `static_assert`：把前提写成编译期检查':'#### 3.1.3 `static_assert`：把前提写成编译期检查',
'## 六、完整示例：转移一帧数据的所有权':'### 3.2 一帧数据的所有权旅程\n\n#### 3.2.1 完整示例：转移一帧数据的所有权',
'## 七、练习与自查':'#### 3.2.2 练习与自查',
}

def parse(text):
    body=[]; headings=[]; codes=[]; fence=None; code=[]
    for line in text.splitlines():
        marker=re.match(r'^\s*(`{3,}|~{3,})',line)
        if fence:
            code.append(line); body.append(line)
            if marker and marker.group(1)[0]==fence[0] and len(marker.group(1))>=len(fence):
                codes.append('\n'.join(code)); code=[]; fence=None
        elif marker:
            fence=marker.group(1); code=[line]; body.append(line)
        elif re.match(r'^#{1,6} ',line): headings.append(line)
        elif line.strip(): body.append(line)
    assert fence is None, 'Unclosed code fence'
    return body,headings,codes

lines=[]; fence=None; applied=Counter()
for line in before.splitlines():
    marker=re.match(r'^\s*(`{3,}|~{3,})',line)
    if fence:
        lines.append(line)
        if marker and marker.group(1)[0]==fence[0] and len(marker.group(1))>=len(fence): fence=None
    elif marker:
        fence=marker.group(1); lines.append(line)
    elif line in changes:
        lines.extend(changes[line].splitlines()); applied[line]+=1
    else: lines.append(line)
assert set(applied)==set(changes) and all(n==1 for n in applied.values())
after='\n'.join(lines)+'\n'
bbody,bheads,bcodes=parse(before); abody,aheads,acodes=parse(after)
assert bbody==abody, 'Non-heading body sequence changed'
assert Counter(bcodes)==Counter(acodes), 'Code content or occurrence count changed'
assert [l for l in bbody if l.startswith('|')]==[l for l in abody if l.startswith('|')]
assert len([h for h in aheads if h.startswith('# ')])==1
assert len([h for h in aheads if h.startswith('## ')])==3
themes=[h for h in aheads if h.startswith('### ')]
assert len(themes)==8
expected=['1.1','1.2','1.3','2.1','2.2','2.3','3.1','3.2']
assert [h.split()[1] for h in themes]==expected
previous_level=0; child_count=Counter()
for heading in aheads:
    level=len(heading)-len(heading.lstrip('#'))
    assert level<=4 and level<=previous_level+1
    previous_level=level
    if level==3: parent=heading.split()[1]
    if level==4:
        child_count[parent]+=1
        assert heading.split()[1]==f'{parent}.{child_count[parent]}'
assert '![' not in after, 'Unexpected image insertion'
newline='\r\n' if b'\r\n' in original else '\n'
DOC.write_bytes(after.replace('\n',newline).encode('utf-8'))
print('PASS: 3 categories, 8 image-theme sections; body sequence, code blocks and tables unchanged.')
print(f'Preserved {len(bcodes)} fenced code blocks; baseline snapshot: {SNAPSHOT}')
print('\n'.join(aheads))
