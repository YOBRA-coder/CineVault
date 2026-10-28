FROM python:3.11-slim

WORKDIR /app

# 1. Copy everything to the container
COPY . .

# 2. Install dependencies for the backend
RUN pip install --no-cache-dir -r backend/requirements.txt

# 3. Expose the port your python app runs on (Render defaults to 10000, change if your app uses 5000 or 8080)
EXPOSE 10000

# 4. Environment variable to ensure output isn't buffered
ENV PYTHONUNBUFFERED=1

# 5. Run the application from the backend folder
CMD ["python", "backend/app.py"]
