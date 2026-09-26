"""场景6：多层调用栈（含递归）
训练点：观察 Call Stack 的深度，Step Out 逐层返回
"""
def factorial(n):
    if n <= 1:          # <-- 断点打在这里（观察递归栈）
        return 1
    return n * factorial(n - 1)

def top():
    return factorial(4)

def main():
    result = top()
    print(result)

main()
