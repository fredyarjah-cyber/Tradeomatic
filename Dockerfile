FROM python:3.12-slim AS python-base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Generate explicitly labeled synthetic demonstration assets from source.
FROM python-base AS demo-assets
COPY . .
RUN mkdir -p src dist reports && python -m scripts.build_demo

FROM node:22-slim AS dashboard
WORKDIR /app
COPY --from=demo-assets /app /app
RUN npm ci && npm run build && cp src/style.css dist/app.css

FROM python-base AS runtime
COPY --from=dashboard /app /app
RUN python -m scripts.package_source && rm -rf node_modules && useradd -m app && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
