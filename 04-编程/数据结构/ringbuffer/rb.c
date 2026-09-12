typedef struct{
    uint8_t *data;
    size_t head;
    size_t tail;
    size_t size;//size>=2
    size_t overflow_cnt;//状态统计

    void *lock;   // mutex句柄
} ring_buffer_t;




ring_buffer_t* rb_init(size_t size)
{
    if(size < 2) {
        return NULL;
    }
    ring_buffer_t* rb = calloc(1, sizeof(ring_buffer_t));
    if (!rb) {
        return NULL;
    }
    rb->data = malloc(size);
    if (!rb->data) {
        free(rb);
        return NULL;
    }
    rb->size = size;
    rb->lock = xSemaphoreCreateMutex();
    if(!rb->lock)
    {
        free(rb->data);
        free(rb);
        return NULL;
    }
    return rb;
}

void rb_lock_take(ring_buffer_t* rb)
{
    if(rb && rb->lock){
        xSemaphoreTake((SemaphoreHandle_t)rb->lock, portMAX_DELAY);
    }
}

void rb_lock_give(ring_buffer_t* rb)
{
    if(rb && rb->lock){
        xSemaphoreGive((SemaphoreHandle_t)rb->lock);
    }
}



bool rb_clear(ring_buffer_t* rb)
{
    if(!rb){
        return false;
    }
    rb_lock_take(rb);
    rb->head = 0;
    rb->tail = 0;
    rb->overflow_cnt = 0;
    rb_lock_give(rb);
    return true;
}

bool rb_destroy(ring_buffer_t* rb)
{
    rb_lock_take(rb);
    if(rb){
        if(rb->data){
            free(rb->data);
        }
        rb_lock_give(rb);
        if(rb->lock)
        {
            vSemaphoreDelete((SemaphoreHandle_t)rb->lock);
        }
        free(rb);
        return true;
    }
    return false;
}



bool rb_is_empty(ring_buffer_t* rb){
    if(!rb){
        return true;//异常时默认为空
    }
    rb_lock_take(rb);
    bool val = rb->head == rb->tail;
    rb_lock_give(rb);
    return val;
}

bool rb_is_full(ring_buffer_t* rb)
{
    if(!rb){
        return false;
    }
    rb_lock_take(rb);
    size_t next = rb->head + 1;
    if(next >= rb->size){
        next = 0;
    }
    bool val = (next == rb->tail);
    rb_lock_give(rb);
    return val;
}

size_t rb_get_used(ring_buffer_t* rb){
    if(!rb){
        return 0;
    }
    rb_lock_take(rb);
    size_t used_space = 0;
    if(rb->head >= rb->tail){
        used_space = rb->head - rb->tail;
    } else{
        used_space = rb->size - (rb->tail - rb->head);
    }
    rb_lock_give(rb);
    return used_space;
}

size_t rb_get_free(ring_buffer_t* rb){
    if(!rb){
        return 0;
    }
    rb_lock_take(rb);
    size_t free_space = 0;
    if(rb->head >= rb->tail){
        free_space = rb->size - (rb->head - rb->tail) - 1;
    } else{
        free_space = rb->tail - rb->head - 1;
    }
    rb_lock_give(rb);
    return free_space;
}

static size_t s_rb_get_used(ring_buffer_t* rb){
    if(!rb){
        return 0;
    }
    size_t used_space = 0;
    if(rb->head >= rb->tail){
        used_space = rb->head - rb->tail;
    } else{
        used_space = rb->size - (rb->tail - rb->head);
    }
    return used_space;
}

static size_t s_rb_get_free(ring_buffer_t* rb){
    if(!rb){
        return 0;
    }
    size_t free_space = 0;
    if(rb->head >= rb->tail){
        free_space = rb->size - (rb->head - rb->tail) - 1;
    } else{
        free_space = rb->tail - rb->head - 1;
    }
    return free_space;
}


int rb_put(ring_buffer_t* rb, const uint8_t* data, size_t len){
    if(!rb||!data){
        return -1;
    }
    if(len==0){
        return 0;
    }
    rb_lock_take(rb);
    size_t free_space = s_rb_get_free(rb);
    size_t wlen = free_space>=len?len:free_space;
    if(wlen<len){
        rb->overflow_cnt++;
    }
    for(size_t i = 0; i<wlen; i++){
        rb->data[rb->head] = data[i];
        rb->head++;
        if((rb->head) >= rb->size){
            rb->head=0;
        }
    }
    rb_lock_give(rb);
    return wlen;
}

int rb_get(ring_buffer_t* rb, uint8_t* data, size_t len){
    if(!rb||!data){
        return -1;
    }
    if(len==0){
        return 0;
    }
    rb_lock_take(rb);
    size_t use_space = s_rb_get_used(rb);
    size_t rlen = use_space>=len?len:use_space;
    for(size_t i = 0; i<rlen; i++){
        data[i] = rb->data[rb->tail];
        rb->tail++;
        if((rb->tail) >= rb->size){
            rb->tail=0;
        }
    }
    rb_lock_give(rb);
    return rlen;
}
