# Auth/users backend service.
# Build context: repo root.  CI: deploy-backend.yml runs `docker build -f backend/Dockerfile .`
FROM python:3.11-slim

WORKDIR /app/backend

# Install deps first for layer caching — only re-runs if requirements change.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the backend/ service code (not api/, frontend/, fixtures/).
COPY backend/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]