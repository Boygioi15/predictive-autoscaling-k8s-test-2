FROM python:3.12-slim

ARG KUBECTL_VERSION=v1.35.5

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORKER_E2E_SCRIPT_PATH=/workspace/linux-script/create-worker-e2e.sh

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      bash \
      ca-certificates \
      curl \
      openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl

WORKDIR /workspace

COPY linux-script/ /workspace/linux-script/

RUN chmod +x /workspace/linux-script/*.sh

CMD ["/bin/bash", "-lc", "echo worker-ops image ready"]
