"""场景1：同文件函数调用
训练点：Step Over vs Step Into 的基础区分
"""
def greet(name):
    return f"Hello, {name}!"

def main():
    name = "World"
    message = greet(name)      # <-- 断点打在这里
    print(message)

main()
