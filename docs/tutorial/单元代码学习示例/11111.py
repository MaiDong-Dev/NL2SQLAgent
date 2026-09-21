def decorator(x):
    # 装饰器外层局部变量
    outer_var = 100

    def wrapper(*args, **kwargs):
        # wrapper 闭包捕获了 outer_var 和原函数 x
        print(f"拿到装饰器内部变量：{outer_var}")
        return x(*args, **kwargs)  # 执行原始函数

    return wrapper

@decorator
def add(a, b):
    return a + b

if __name__ == '__main__':
    print(add(1, 2))