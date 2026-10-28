# Stage 1: Build the Application
FROM python:3.11-slim AS build

WORKDIR /usr/src/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create the virtual environment inside the build container
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy your full project directory (so backend/requirements.txt is available)
COPY . .

# Install dependencies from your backend folder
RUN pip install --upgrade pip && \
    pip install -r backend/requirements.txt

# Stage 2: Create the Final Production Image
FROM python:3.11-slim

WORKDIR /usr/src/app

# Copy the environment and project code from the builder stage
COPY --from=build /opt/venv /opt/venv
COPY --from=build /usr/src/app .

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Create a non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /usr/src/app
USER appuser

# Set the fallback port (matching Render's 10000 or custom)
ENV PORT=10000
EXPOSE $PORT

# CORRECTED: Point to your backend app file
CMD ["python", "backend/app.py"]
