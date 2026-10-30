FROM python:3.12-slim

# Docker CLI only (no daemon): the API launches sandbox containers via the host's docker.sock
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && printf 'enable_metrics=false\n' > /root/.guardrailsrc

COPY app ./app
COPY sandbox ./sandbox
COPY sample_data ./sample_data

ENV PYTHONUNBUFFERED=1 OTEL_SDK_DISABLED=true CREWAI_DISABLE_TELEMETRY=true
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
