FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VITE_DEV_HOST=0.0.0.0 \
    VITE_ALLOW_ALL_HOSTS=true \
    LUMINA_BACKEND=memory \
    LUMINA_MATERIALS_DIR=/app/materials \
    LUMINA_LOG_DIR=/app/logs \
    LUMINA_FEEDBACK_DUMP_DIR=/app/feedback \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1

# System dependencies:
# - cairo/pkg-config/OpenGL libs are required by the image and mesh pipeline.
# - node/npm/pnpm are required to build the frontend dist during image build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gcc \
    g++ \
    git \
    libcairo2-dev \
    libgl1 \
    libglib2.0-0 \
    make \
    nodejs \
    npm \
    pkg-config \
    && npm install -g pnpm@10.33.2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-glb-v2.txt /app/
RUN pip install --no-cache-dir -r requirements.txt -r requirements-glb-v2.txt

COPY frontend/package.json frontend/pnpm-lock.yaml /app/frontend/
RUN cd frontend && pnpm install --frozen-lockfile

COPY . /app/
RUN cd frontend && pnpm build

ARG MATERIALS_SEED_URL=""
ARG MATERIALS_SEED_SHA256=""
RUN mkdir -p /app/resources/materials \
    && if [ -n "$MATERIALS_SEED_URL" ]; then \
        curl -fL "$MATERIALS_SEED_URL" -o /app/resources/materials/lumina-materials-seed.zip; \
        if [ -n "$MATERIALS_SEED_SHA256" ]; then \
            echo "$MATERIALS_SEED_SHA256  /app/resources/materials/lumina-materials-seed.zip" | sha256sum -c -; \
        fi; \
    fi

ENV LUMINA_SERVE_FRONTEND_DIST=1 \
    LUMINA_FRONTEND_DIST_DIR=/app/frontend/dist
RUN mkdir -p /app/output /app/logs /app/feedback /app/materials

EXPOSE 8000

CMD ["python", "api_server.py"]
