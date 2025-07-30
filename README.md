# RoboPost2

This project is a Telegram bot service using `python-telegram-bot`.

## Requirements
- Docker and Docker Compose
- `python-telegram-bot` version 20.7 (installed automatically from `requirements.txt`)

## Deployment
To build the Docker images and start the services run:

```bash
docker-compose up --build
```

This ensures the correct version of `python-telegram-bot` supporting the `Defaults` class is installed.