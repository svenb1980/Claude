# 32-bit Raspberry Pi OS needs PYTHON_VERSION=3.11, the newest Python with ready-made builds of the
# packages for armv7 (from piwheels.org). Set it in .env there. Other machines keep 3.12.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /srv
COPY requirements.txt requirements-armv7.txt ./
RUN if [ "$(uname -m)" = "armv7l" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends libopenblas0-pthread libgfortran5 libxml2 libxslt1.1 \
        && rm -rf /var/lib/apt/lists/* \
        && pip install --no-cache-dir --prefer-binary --extra-index-url https://www.piwheels.org/simple \
            -r requirements-armv7.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY app ./app

RUN useradd --create-home --uid 1000 analyzer \
    && mkdir -p /data \
    && chown analyzer:analyzer /data
USER analyzer
VOLUME /data

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
