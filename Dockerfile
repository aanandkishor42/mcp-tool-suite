FROM python:3.13-slim AS builder
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && pip wheel --no-deps --wheel-dir /wheels .
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TRANSPORT=streamable-http \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/data/index
RUN addgroup --system --gid 1001 appgroup \
    && adduser --system --uid 1001 --ingroup appgroup appuser
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl
COPY src ./src
RUN mkdir -p /data/index && chown -R appuser:appgroup /app /data
USER appuser
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"
CMD ["mcp-tool-suite"]
