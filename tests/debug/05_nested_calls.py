"""场景5：一个语句里嵌套多个函数调用
训练点：理解 Python 从左到右、由内而外的求值顺序
"""
def add(a, b):
    return a + b

def double(x):
    return x * 2

def inc(y):
    return y + 1

def main():
    result = add(double(inc(3)), double(4))   # <-- 断点打在这里
    print(result)

main()
