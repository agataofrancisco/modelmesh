# Imagem do gateway. Verificada com Docker em 2026-11-27.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY gateway ./gateway
COPY migrations ./migrations
COPY alembic.ini ./

# Utilizador sem privilégios; o código é só de leitura.
RUN useradd --create-home --uid 10001 modelmesh && chown -R modelmesh /app
USER modelmesh

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"

# As migrações correm como passo separado (ver docker-compose.yml, serviço `migrate`).
CMD ["uvicorn", "gateway.app.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
