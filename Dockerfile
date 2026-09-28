FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends fuse libfuse2 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m alice && useradd -m bob && useradd -m carol
WORKDIR /opt/topos
COPY pyproject.toml ./
COPY topos ./topos
RUN pip install --no-cache-dir -e '.[fuse,test]'
COPY tests ./tests
COPY ejemplos ./ejemplos
COPY demo.sh entrar.sh ./
CMD ["bash", "demo.sh"]
