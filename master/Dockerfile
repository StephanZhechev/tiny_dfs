# Use an official Python runtime as a base image
FROM python:3.12.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
RUN pip install --upgrade pip && pip install pysyncobj fastapi uvicorn httpx tenacity

RUN mkdir -p /home/data
RUN touch /home/data/log.jsonl
RUN touch /home/data/in_memory_catalog_snapshot.json

# Copy the master script.
COPY main.py /app/main.py
COPY src/ /app/src/
WORKDIR /app

# Expose the port (optional – not strictly needed since ports aren’t published externally).
EXPOSE 8001 8002 8003

CMD ["python", "main.py"]
