"""场景2：多层函数调用 main -> A -> B -> C
训练点：Step Into 逐层进入，Step Out 逐层跳出
"""
def C():
    return 30

def B():
    x = C()      # 调用 C
    return x + 20

def A():
    y = B()      # 调用 B
    return y + 10

def main():
    result = A()   # <-- 断点打在这里
    print(result)

main()
