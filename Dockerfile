FROM seleniumbase/seleniumbase:latest

WORKDIR /app

# The official image already has Chrome, Xvfb, and all dependencies.
# Just copy your app and install Flask.
COPY app.py .
RUN pip3 install flask

ENV PORT=10000
EXPOSE 10000

CMD ["python3", "app.py"]
