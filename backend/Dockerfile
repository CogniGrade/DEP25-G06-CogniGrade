# backend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# copy dependency list
COPY ../requirements.txt /app/

RUN pip install --no-cache-dir -r requirements.txt

# copy your FastAPI code
COPY . /app/

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
