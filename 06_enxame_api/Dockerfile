# enxame-api — container próprio no VPS (NÃO fazer deploy sem green light)
#
# A imagem instala SÓ o requirements.txt (produção). O pytest e o Playwright ficam
# no requirements-dev.txt: o primeiro não é importado por nada em app/, e o segundo
# pesava 136 MB para um motor que esta imagem não consegue executar (sem Chromium).
# Aqui roda só o motor 'http' — por decisão, não por acidente.
FROM python:3.12-slim

WORKDIR /srv/enxame-api

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
