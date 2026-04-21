# Player valuation API service.
# Build context: repo root.  CI: .github/workflows/api.yml builds with `docker build .`
FROM python:3.11-slim

WORKDIR /app

# Install deps first for layer caching — only re-runs if requirements change.
COPY api/requirements.txt ./api/
RUN pip install --no-cache-dir -r api/requirements.txt

# Copy only the api/ service code (not backend/, frontend/, fixtures/).
# Preserves the `api` package namespace so `api.main:app` import works.
COPY api/ ./api/

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
