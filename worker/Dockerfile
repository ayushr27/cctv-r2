FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install CPU-only torch first to avoid pulling the 1.5 GB CUDA stack
RUN pip install --no-cache-dir --timeout=300 \
    torch==2.4.0 torchvision==0.19.0 \
    --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --timeout=300 -r requirements.txt

COPY . .

# Pre-download YOLOv8n weights so the container works offline after first build
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

CMD ["python", "-c", "print('worker ready')"]
