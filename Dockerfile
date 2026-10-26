FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wget gnupg unzip curl xvfb x11-utils \
    libxss1 libasound2 libatk-bridge2.0-0 libgtk-3-0 libnss3 \
    && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN which google-chrome || which google-chrome-stable || echo "CHROME NOT FOUND"

ENV PORT=10000
EXPOSE 10000

CMD ["python", "app.py"]
