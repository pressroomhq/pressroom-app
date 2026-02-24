FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build frontend
RUN apt-get update && apt-get install -y nodejs npm && \
    cd frontend && npm install && npm run build && \
    apt-get purge -y nodejs npm && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* frontend/node_modules

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
