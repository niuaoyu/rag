"""场景3 的辅助模块：被 03_cross_file.py 调用
"""
def helper(num):
    return num * 2

def another(n):
    return helper(n) + 1
