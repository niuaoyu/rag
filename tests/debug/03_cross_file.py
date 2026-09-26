"""场景3：跨文件函数调用
依赖 03_lib.py
训练点：Step Into 会跳进另一个文件
"""
from lib_03 import helper, another

def main():
    a = helper(5)      # <-- 断点打在这里
    b = another(a)
    print(a, b)

main()
