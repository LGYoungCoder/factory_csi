# Factory CSI backend: FastAPI + LangGraph + Industrial MCP Server (stdio subprocess) + simulator
ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX} UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir --index-url ${UV_DEFAULT_INDEX} uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY factory_data ./factory_data
COPY simulator ./simulator
COPY industrial_mcp ./industrial_mcp
COPY backend ./backend
COPY evaluation ./evaluation
COPY docker/entrypoint.sh ./docker/entrypoint.sh
RUN uv sync --frozen --no-dev && useradd --create-home --uid 10001 app \
    && mkdir -p /app/data /app/var /app/logs && chown -R app /app/data /app/var /app/logs && chmod +x docker/entrypoint.sh
USER app
ENV PATH=/app/.venv/bin:$PATH DATA_DIR=/app/data APP_DB_PATH=/app/var/app.db CHECKPOINT_DB_PATH=/app/var/checkpoints.db \
    LOG_DIR=/app/logs HOST=0.0.0.0 PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["/app/docker/entrypoint.sh"]
