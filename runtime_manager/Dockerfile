FROM python:3.10

WORKDIR /app
COPY runtime_manager/ .
COPY dataformats ./src/dataformats
COPY demo_system/ ./demo_system

RUN pip install --no-cache-dir -r requirements.txt

# start REST-API server of runtime manager
CMD python src/runtime_manager.py
