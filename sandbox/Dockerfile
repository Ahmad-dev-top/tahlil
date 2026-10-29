# Minimal image that runs agent-written analysis code. No network at runtime (--network none).
FROM python:3.12-slim
RUN pip install --no-cache-dir pandas==2.2.* matplotlib==3.9.* numpy==2.* \
    && useradd --uid 10001 --no-create-home sandbox
COPY runner.py /sandbox/runner.py
ENV MPLCONFIGDIR=/tmp PYTHONDONTWRITEBYTECODE=1
USER 10001
WORKDIR /work
CMD ["python", "/sandbox/runner.py"]
