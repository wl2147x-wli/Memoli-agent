ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /workspace

# 镜像只提供固定 Python 运行时；运行期不安装依赖，也不声明宿主入口。
CMD ["python", "--version"]
