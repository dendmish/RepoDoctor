# RepoDoctor app image
# Стадия docker-cli нужна, чтобы приложение само умело запускать
# чуж проекты в песочнице через docker.sock хоста.
ARG DOCKERCLI=docker:cli
ARG BASE=python:3.12-slim

FROM ${DOCKERCLI} AS dockercli
FROM ${BASE}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY repodoctor/ ./repodoctor/
COPY prompts/ ./prompts/
COPY examples/ ./examples/

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.headless=true"]
