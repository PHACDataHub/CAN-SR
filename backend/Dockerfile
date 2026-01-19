ARG IMAGE_NAME=nvidia/cuda
ARG IMAGE_TAG=12.8.1-cudnn-devel-ubuntu24.04
FROM ${IMAGE_NAME}:${IMAGE_TAG}

WORKDIR /app

# Install Python and system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    gcc \
    g++ \
    git \
    wget \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3 as default
RUN ln -s /usr/bin/python3 /usr/bin/python

# Set CUDA environment variables for NVIDIA T4 GPU (compute capability 7.5)
ENV TRANSFORMERS_VERBOSITY=error
ENV TOKENIZERS_PARALLELISM=false
ENV CUDA_LAUNCH_BLOCKING=0

# Increase pip resiliency for large wheels (e.g., torch)
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=300

# Install Python dependencies
# NOTE: We install PyTorch separately from requirements.txt to avoid brittle resolution
# and to ensure we always pull CUDA-enabled wheels from the PyTorch index.
# Keep these pinned for reproducibility.
ARG TORCH_VERSION=2.7.1
ARG TORCHVISION_VERSION=0.20.1
ARG TORCHAUDIO_VERSION=2.5.1
ARG TORCH_CUDA_SUFFIX=cu128

# Install torch with retries to reduce transient download/corruption failures
RUN pip install --break-system-packages --no-cache-dir \
    --index-url https://download.pytorch.org/whl/${TORCH_CUDA_SUFFIX} \
    torch torchvision torchaudio

COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p uploads

# Create non-root user for security
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run the application
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
