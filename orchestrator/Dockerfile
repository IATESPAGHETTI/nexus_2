# Orchestrator service (HTTP trigger for investigations). Build context = repository root:
#   docker build -f orchestrator/Dockerfile -t nexus-orchestrator .
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8

COPY orchestrator/requirements.txt orchestrator-requirements.txt
RUN pip install --no-cache-dir -r orchestrator-requirements.txt uvicorn==0.53.0 starlette==1.6.0

COPY runtime_config.py nexus_models.py nexus_guard.py nexus_trace.py ./
COPY orchestrator ./orchestrator
COPY agents/common ./agents/common
COPY guardrails ./guardrails

ENV NEXUS_BIND_HOST=0.0.0.0
RUN useradd --create-home --uid 10001 nexus && mkdir -p /app/guardrails && chown -R nexus /app/guardrails
USER nexus
EXPOSE 8200
CMD ["python", "orchestrator/service.py"]
