#include <stddef.h>
#include <stdint.h>

void* memcpy(void* dest, const void* src, size_t n)
{
    if(!dest|| !src)
        return NULL;

    char* dst = (char*)dest;
    const char* s = (const char*)src;

    while(n--){
        *dst++ = *s++;
    }
    
    return dest;
}




void* memmove(void* dest, const void* src, size_t n)
{
    if(!dest|| !src)
        return NULL;

    char* dst = (char*)dest;
    const char* s = (const char*)src;

    if((uintptr_t)dst>(uintptr_t)s){
        dst += n -1;
        s += n -1;
        while(n--){
            *dst-- = *s--;//先赋值，后减减
        }
    }
    else{
        while(n--){
            *dst++ = *s++;
        }
    }
    
    
    return dest;
}


void *strcpy(char* dst, const char* src)
{
    if(!dst|| !src)
        return NULL;

    while(*src!="\0"){
        *dst++ = *src++;
    }
    *dst = '\0';
    return dst;
}



void *strncpy(char* dst, const char* src, size_t n)
{
    if(!dst|| !src)
        return NULL;

    for(size_t i=0; i<n && src[i]!='\0'; i++){
        dst[i] = src[i];
    }

    if(n > 0) {
        dst[n - 1] = '\0';
    }
    return dst;
}

// ab'\0' 
size_t strlen(const char* s)
{
    if(!s)
        return 0;

    size_t len = 0;
    while(*s++){
        len++;
    }
    return len;
}


// 如果两个字符串相等，返回0；如果s1大于s2，返回正数；如果s1小于s2，返回负数
int strcmp(const char* s1, const char* s2)
{
    if(!s1 || !s2)
        return 0;

    while(*s1 && (*s1 == *s2)){
        s1++;
        s2++;
    }
    return *s1 - *s2;
}

// 如果两个字符串相等，返回0；如果s1大于s2，返回正数；如果s1小于s2，返回负数
int strncmp(const char* s1, const char* s2, size_t n)
{
    if(!s1 || !s2)
        return 0;

    while(*s1 && (*s1 == *s2) && n > 0){
        s1++;
        s2++;
        n--;
    }
    return *s1 - *s2;
}