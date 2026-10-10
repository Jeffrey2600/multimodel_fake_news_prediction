# Hugging Face Space build file.
# The Space only holds this Dockerfile and README.md; the app itself is pulled from GitHub,
# so redeploying after a push is just "Factory rebuild" in the Space settings.

FROM python:3.12-slim AS src
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
# changes whenever main moves, so a rebuild always fetches the latest code
ADD https://api.github.com/repos/Jeffrey2600/multimodel_fake_news_prediction/git/refs/heads/main /tmp/version.json
RUN git clone --depth 1 https://github.com/Jeffrey2600/multimodel_fake_news_prediction.git /src

FROM node:20-slim AS web
WORKDIR /web
COPY --from=src /src/frontend/package.json /src/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=src /src/frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 HOME=/tmp HF_HOME=/tmp/hf PORT=7860
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=src /src/backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY --from=src /src/backend/ backend/
COPY --from=web /web/dist frontend/dist
RUN useradd -m -u 1000 user && mkdir -p backend/data && chown -R user /app
USER user
WORKDIR /app/backend
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
