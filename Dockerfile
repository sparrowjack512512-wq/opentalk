# Use the official SeleniumBase image which has Python 3.13, Chrome, and Xvfb pre-installed
FROM seleniumbase/seleniumbase:latest

WORKDIR /app

# Copy your app and install Flask (and proxy auth if needed)
COPY app.py .
RUN pip3 install flask selenium-proxy-auth

ENV PORT=10000
EXPOSE 10000

# CRITICAL: Use python3 (not python) to run the modern Python version
CMD ["python3", "app.py"]
