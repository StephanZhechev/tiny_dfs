# Use an official Python runtime as a base image
FROM python:3.12.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
RUN pip install --upgrade pip && pip install fastapi uvicorn python-multipart aiohttp httpx tenacity

# Copy the rest of the application code into the container
COPY . .

# Expose the port that the master listens on
EXPOSE 10001 10002 10003 10004 10005

# Run the master application
CMD ["python", "main.py"]
