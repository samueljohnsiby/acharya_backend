# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables to ensure the output is logged to the console
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Install build dependencies and clean up to keep the image slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY ./requirements.txt /app/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

# Copy the rest of the application code into the container
COPY . /app

# Expose the port FastAPI runs on
EXPOSE 8000

# Add GEMINI_API_KEY as an environment variable
ENV GEMINI_API_KEY=""
ENV API_KEY=""


# Command to run the FastAPI app using gunicorn and uvicorn worker for production
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "main:app", "--bind", "0.0.0.0:8000", "--workers", "4"]
