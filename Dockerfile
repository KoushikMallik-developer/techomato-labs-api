FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Set to "true" to also install the test tooling (pytest, ...).
ARG INSTALL_DEV=false

COPY requirements.txt requirements-dev.txt ./
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; else pip install -r requirements.txt; fi

# Run as an unprivileged user; /var/app/static holds collected admin assets.
ARG APP_UID=1000
RUN useradd --create-home --uid ${APP_UID} app \
    && mkdir -p /var/app/static \
    && chown -R app:app /var/app /app
USER app

COPY --chown=app:app . .
# Guard against CRLF line endings when the repo was checked out on Windows.
RUN sed -i 's/\r$//' scripts/*.sh

ENV STATIC_ROOT=/var/app/static
EXPOSE 8000

CMD ["sh", "scripts/start-web.sh"]
