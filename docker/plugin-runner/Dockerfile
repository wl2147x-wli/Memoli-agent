# 基础镜像必须由构建脚本以 sha256 digest 传入，避免标签漂移。
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/memoli
WORKDIR /opt/memoli

# runner 不在运行时安装任何依赖；镜像只包含协议和插件公共合同。
COPY memoli_agent /opt/memoli/memoli_agent

USER 65532:65532
ENTRYPOINT ["python", "-m", "memoli_agent.agent.plugins.runner"]
