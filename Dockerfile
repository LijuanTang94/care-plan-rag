FROM python:3.12-slim

WORKDIR /app

# libgomp1: required by fastembed's onnxruntime (not included in the slim image by default)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application package + migrations + eval/test scripts + their config
COPY careplan/ ./careplan/
COPY eval/ ./eval/
COPY tests/ ./tests/
COPY alembic/ ./alembic/
COPY alembic.ini pytest.ini ./

EXPOSE 8000
CMD ["uvicorn", "careplan.main:app", "--host", "0.0.0.0", "--port", "8000"]
