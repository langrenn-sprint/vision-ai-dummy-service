FROM python:3.11

RUN mkdir -p /app
WORKDIR /app

RUN pip install --upgrade pip
RUN pip install "poetry==1.7.1"
COPY poetry.lock pyproject.toml /app/

# Docker label
LABEL org.opencontainers.image.source=https://github.com/langrenn-sprint/vision-ai-service
LABEL org.opencontainers.image.description="vision-ai-service"
LABEL org.opencontainers.image.licenses=Apache-2.0

# Project initialization:
RUN poetry config virtualenvs.create false \
  && poetry install --no-dev --no-interaction --no-ansi

ADD vision-ai-service /app/vision-ai-service

RUN apt-get update && apt-get install -y libgl1-mesa-glx

# RUN pip install gunicorn
# CMD gunicorn  "vision-ai-service:create_app"
CMD python3 vision-ai-service/app.py