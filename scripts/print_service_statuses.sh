#!/bin/bash

# Сохраняет статусы supervisor-сервисов в json-файл.

# Файл для записи результата.
status_file="/opt/web/service_statuses.json"

# Список сервисов для обработки.
services=(
  "beeline_service"
  "celery_flower"
  "celery_worker"
  "download_attempt_speechka"
  "jobs_speechka"
  "mango_service"
  "server_444_speechka"
  "server_speechka"
  "sipuni_speechka"
  "speechka"
  "upload_google_speechka"
  "zoom_service"
  )


# Начало содержимого JSON.
json_output="{\"last_check\": \"$(date '+%Y-%m-%d %H:%M:%S')\", \"services\": ["

status_output=$(supervisorctl status)

# Перебираем все сервисы из списка.
for service in "${services[@]}"; do
    # Ищем строку статуса для конкретного сервиса
    status=$(echo "$status_output" | grep "^$service" | awk '{print $2}')
    # Если сервис не найден, указываем статус "unavailable".
    if [ -z "$status" ]; then
        status="unavailable"
    fi
    # Сохраняем результат для сервиса.
    json_output+="{\"name\": \"$service\", \"status\": \"$status\"},"
done
# Убираем последнюю запятую, если есть.
json_output=$(echo "$json_output" | sed 's/,$//')
json_output+="]}"


echo $json_output > "$status_file"
