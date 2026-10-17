FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# The venv lives outside /project so mounting ./app for live reload never hides it.
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /project

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

# data/ holds the generated token-encryption key when PERSONAL_OS_SECRET_KEY is unset.
RUN useradd --create-home --uid 1000 app && mkdir -p /project/data && chown app:app /project/data
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
