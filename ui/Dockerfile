FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 --create-home comeblog
COPY streamlit_app.py .
USER comeblog
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2)"
CMD ["streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
