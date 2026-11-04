FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 COMEBLOG_OUTPUT_DIR=/data/output
COPY --from=build /install /usr/local
RUN useradd --system --uid 10001 --create-home comeblog \
    && mkdir -p /data/output && chown -R comeblog /data
USER comeblog
WORKDIR /home/comeblog
VOLUME /data/output
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
