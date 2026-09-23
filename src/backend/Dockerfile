FROM python:3.11-slim

WORKDIR /app

COPY requirements-processing.txt .
# The API performs local CPU inference. Prefer PyTorch's CPU wheel index so an
# ARM64 build does not download NVIDIA CUDA packages, while PyPI supplies the
# remaining pinned dependencies. Retries cover transient large-wheel downloads.
RUN pip install --no-cache-dir --timeout 120 --retries 5 \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    -r requirements-processing.txt

COPY . .

# The build is the only network-enabled model preparation step. The child sets
# offline flags before loading these pinned assets at runtime.
RUN python -m spacy validate \
 && python -m app.processing.embeddings --download

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
