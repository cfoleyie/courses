# Playwright's own image already carries Chromium and its system libraries,
# which is most of the pain of running a browser in a container.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY switchtime ./switchtime

RUN pip install --no-cache-dir -e .

ENV SWITCHTIME_CONFIG=/app/config.toml
EXPOSE 8777
VOLUME ["/app/data"]

CMD ["switchtime", "serve"]
