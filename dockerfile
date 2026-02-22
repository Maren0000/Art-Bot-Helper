FROM python:3.14.2-slim

WORKDIR /app
COPY ./requirements.txt /app

RUN apk add --no-cache git

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt