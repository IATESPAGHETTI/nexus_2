# One image for all 7 ADK agent services; docker-compose picks the service with `command:`.
# Build context = repository root:  docker build -f agents/Dockerfile -t nexus-agents .
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8

COPY agents/requirements.txt agents-requirements.txt
RUN pip install --no-cache-dir -r agents-requirements.txt

COPY runtime_config.py nexus_models.py nexus_guard.py nexus_trace.py ./
COPY agents ./agents
COPY mcp ./mcp

# The MCP server (stdio) runs with this same interpreter: mcp[cli] and httpx are in agents/requirements.txt.
ENV NEXUS_MCP_PYTHON=python NEXUS_BIND_HOST=0.0.0.0
RUN useradd --create-home --uid 10001 nexus
USER nexus
CMD ["python", "agents/metrics/a2a_service.py"]
