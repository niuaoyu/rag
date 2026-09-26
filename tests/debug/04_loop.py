"""场景4：循环中的函数调用
训练点：Step Over 在循环里逐次执行；Step Into 进入循环体内的函数
"""
def square(n):
    return n * n

def main():
    total = 0
    for i in range(3):      # <-- 断点打在这里
        total += square(i)  # 循环体内调用函数
    print(total)

main()
