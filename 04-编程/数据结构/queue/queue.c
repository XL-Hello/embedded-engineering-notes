// 基于链表的通用消息队列，单生产者单消费者模式，非线程安全

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>

// 对外
typedef struct {
    int type;
    size_t len;
    uint8_t data[];
}msg_t;


// 内部隐藏
typedef struct msg_node {
    msg_t *msg;
    struct msg_node *next;
} msg_node_t;


// 对外
typedef struct {
    msg_node_t* head; //dummy node
    msg_node_t* tail;
    size_t size;
    size_t size_max;
}msg_queue_t;


// 队列初始化
msg_queue_t* msg_queue_init(size_t size_max)
{
    msg_queue_t* queue = (msg_queue_t*)calloc(1, sizeof(msg_queue_t));
    if(!queue){
        return NULL;
    }
    queue->size_max = size_max;
    // 创建一个空node作为头结点
    queue->head = (msg_node_t*)calloc(1, sizeof(msg_node_t));
    if(!queue->head){
        free(queue);
        return NULL;
    }
    queue->tail = queue->head;//head==tail表示队列为空
    queue->size = 0;
    return queue;
}

// 向队列中放入消息
int msg_queue_put(msg_queue_t* queue, msg_t* msg)
{
    if(!queue||!msg){
        return -1;
    }

    // 检查队列是否已满
    if(queue->size >= queue->size_max){
        return -1; // 队列已满
    }

    // 创建一个新节点
    msg_node_t* new_node = (msg_node_t*)calloc(1, sizeof(msg_node_t));
    if(!new_node){
        return -1; // 内存分配失败
    }
    new_node->msg = msg;
    new_node->next = NULL;

    // 将新节点添加到队列尾部
    queue->tail->next = new_node;// 加入链表
    queue->tail = new_node;      // 更新尾指针
    queue->size++;               // 更新队列大小

    return 0;
}

//获取队列大小，返回有效的消息数量
int msg_queue_get_size(msg_queue_t* queue)
{
    if(!queue){
        return -1;
    }
    return queue->size;
}

// 取出队列中的消息
msg_t* msg_queue_get(msg_queue_t* queue)
{
    if(!queue){
        return NULL;
    }

    // 检查队列是否为空
    if(queue->size == 0){
        return NULL; // 队列为空
    }

    // 先取出head节点消息
    msg_node_t* head_node = queue->head;     //dummy node
    msg_node_t* next_node = head_node->next; // 取出的节点

    //取数据 赋值msg
    msg_t* msg = next_node->msg;

    // 更新指针
    queue->head->next = next_node->next;
    queue->size--;
    if(0==queue->size){
        queue->tail = queue->head; // 队列为空时，tail指向head
    }

    free(next_node);
    return msg;
}

// 释放一个消息
int msg_destroy(msg_t* msg)
{
    if(!msg){
        return -1;
    }
    free(msg);
    return 0;
}


