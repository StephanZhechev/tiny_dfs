# Use an official Python runtime as a base image
FROM python:3.12.9-slim

# Set the working directory in the container
WORKDIR /app

RUN pip install --upgrade pip && pip install fastapi uvicorn httpx pysyncobj aiohttp tenacity

# Copy the rest of the application code into the container
COPY main.py /app/main.py

# EXPOSE 8001 8002 8003 # Not needed at all

# Define environment variables if needed (optional)
# ENV NODE_ADDRESS=master-0
# ENV CLUSTER_NODES=master-0:8000,master-1:8000,master-2:8000

# Run the master application
CMD ["python", "main.py"]
