FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY trolley ./trolley

RUN pip install --no-cache-dir -e .

ENV TROLLEY_CONFIG=/app/config.toml
EXPOSE 8815
VOLUME ["/app/data"]

CMD ["trolley", "serve"]
