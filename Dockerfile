FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TRANSPORT=streamable-http \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/data/index

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

VOLUME ["/data/index"]
EXPOSE 8000

CMD ["mcp-tool-suite"]
