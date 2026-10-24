# CrewAI Root-Cause Critic served over A2A (own image: CrewAI and the ADK stack pin different a2a-sdk versions).
# Build context = repository root:  docker build -f crewai_critic/Dockerfile -t nexus-crewai-critic .
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 CREWAI_DISABLE_TELEMETRY=true OTEL_SDK_DISABLED=true

COPY crewai_critic/requirements.txt crewai-requirements.txt
RUN pip install --no-cache-dir -r crewai-requirements.txt

COPY nexus_models.py nexus_guard.py nexus_trace.py runtime_config.py ./
COPY agents/common ./agents/common
COPY agents/critic ./agents/critic
COPY agents/evidence ./agents/evidence
COPY crewai_critic ./crewai_critic

ENV NEXUS_BIND_HOST=0.0.0.0 CRITIC_PORT=8106
RUN useradd --create-home --uid 10001 nexus
USER nexus
CMD ["python", "crewai_critic/a2a_service.py"]
