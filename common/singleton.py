def singleton(cls):
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    # 公开未修饰的类，以便合法需要的调用者超过
    # 一个实例（例如，运行同一通道类型的多个实例，
    # 每个都有自己的凭据）可以绕过进程范围的缓存。遗产
    # 调用者继续通过 get_instance() 并仍然获得单例。
    get_instance.__wrapped__ = cls

    def new_instance(*args, **kwargs):
        """Build a fresh, uncached instance of the wrapped class."""
        return cls(*args, **kwargs)

    get_instance.new_instance = new_instance

    return get_instance
