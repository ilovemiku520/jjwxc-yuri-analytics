ARG PYURI_PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYURI_PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYURI_ENABLE_NETWORK=false

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir ".[api,postgres]"

RUN addgroup --system --gid 10001 pyuri \
    && adduser --system --uid 10001 --ingroup pyuri --home /nonexistent --no-create-home pyuri

USER pyuri

ENTRYPOINT ["pyuri-schema-probe"]
