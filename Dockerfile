# Use the official SeleniumBase Dockerfile as the base
FROM seleniumbase/seleniumbase:latest

# The official image may have an older Python as default.
# Install a newer Python (e.g., 3.11) and set it as default.
RUN apt-get update && apt-get install -y python3.11 python3.11-venv python3.11-dev \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --set python3 /usr/bin/python3.11 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy your app and install Flask with the new Python
COPY app.py .
RUN python3 -m pip install flask

ENV PORT=10000
EXPOSE 10000

# Run with the new Python
CMD ["python3", "app.py"]
