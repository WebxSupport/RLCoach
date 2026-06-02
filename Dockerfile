FROM python:3.11-slim

# System deps for matplotlib (headless), carball, and extracting the rrrocket binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 curl ca-certificates tar gzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Download rrrocket Linux binary (musl static build — no extra deps).
# Download to a file with --fail so an HTTP error aborts the build cleanly
# instead of piping a 404 page into tar. Extract, then locate the binary
# wherever it lands in the archive.
ARG RRROCKET_VERSION=0.11.1
RUN mkdir -p /app/rrrocket_bin/linux /tmp/rr && \
    curl -fSL "https://github.com/nickbabcock/rrrocket/releases/download/v${RRROCKET_VERSION}/rrrocket-${RRROCKET_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
      -o /tmp/rr/rrrocket.tar.gz && \
    tar -xzf /tmp/rr/rrrocket.tar.gz -C /tmp/rr && \
    cp "$(find /tmp/rr -type f -name rrrocket | head -n1)" /app/rrrocket_bin/linux/rrrocket && \
    chmod +x /app/rrrocket_bin/linux/rrrocket && \
    ln -sf /app/rrrocket_bin/linux/rrrocket /app/rrrocket_bin/rrrocket && \
    rm -rf /tmp/rr && \
    /app/rrrocket_bin/linux/rrrocket --version

ENV RRROCKET_PATH=/app/rrrocket_bin/rrrocket
# Matplotlib non-interactive backend
ENV MPLBACKEND=Agg

# Install Python dependencies
COPY requirements_web.txt .
RUN pip install --no-cache-dir -r requirements_web.txt

# Copy application code
COPY rlcoach/ ./rlcoach/
COPY rlapi/ ./rlapi/
COPY static/ ./static/
COPY web_app.py web_database.py ./

# Create data directory (will be volume-mounted in production)
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000"]
