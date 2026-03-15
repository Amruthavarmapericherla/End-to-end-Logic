# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim AS runtime

# Prevent .pyc files and ensure unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
PYTHONUNBUFFERED=1

# System deps kept minimal (pymongo + pymysql are pure-Python)
RUN apt-get update \
&& apt-get install -y --no-install-recommends \
ca-certificates curl \
&& rm -rf /var/lib/apt/lists/*

# Create non-root user and directories
RUN useradd -m -u 10001 appuser \
&& mkdir -p /app /var/log/tele \
&& chown -R appuser:appuser /app /var/log/tele

WORKDIR /app

# Install Python deps first for better layer caching
# (use a separate requirements.txt if you prefer)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# copy everything from THIS folder into the image
COPY . .

USER appuser

# Default entrypoint (CLI flags can be added via `docker run ... -- <flags>`)
ENTRYPOINT ["python", "app.py"]
