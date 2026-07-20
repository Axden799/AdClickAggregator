# One image, used by BOTH the app and the consumer (they differ only in the
# command they run). Matches the local Python (3.12); slim keeps the image small.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies FIRST, in their own layer. Docker caches layers, and
# requirements.txt changes far less often than the code — so rebuilds after a
# code edit skip the (slow) pip install and reuse this cached layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the application code.
COPY . .

# Default command runs the API. The consumer service in docker-compose overrides
# this with `python -m app.consumer`. --host 0.0.0.0 makes uvicorn listen on all
# interfaces so it's reachable from outside the container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
