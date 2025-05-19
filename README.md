# Речка.ai

Система автоматического анализа телефонных разговоров с использованием искусственного интеллекта.

## Основные возможности

### Источники звонков
- Telegram бот (прямая загрузка аудиофайлов)
- AmoCRM (webhooks)
- Битрикс24 (webhooks)
- Beeline телефония
- Sipuni телефония

### Обработка и анализ
- Транскрибация аудио в текст (AssemblyAI)
- Анализ качества разговоров (Claude AI)
- Автоматическая выгрузка в Google Sheets
- Сохранение в PostgreSQL

### Дополнительно
- Система оплаты (Robokassa)
- Различные режимы анализа
- Реферальная система
- Административный доступ
- REST API

## Структура проекта

### Основные модули (`modules/`)
- `audio_processor.py` - обработка аудиофайлов
- `assembly.py` - интеграция с AssemblyAI (Транскрибация и Анализ)
- `report_generator.py` - генерация отчетов
- `analytics.py` - статистика и аналитика

### Интеграции (`integrations/`)
- `amo_crm/` - AmoCRM интеграция
- `bitrix/` - Битрикс24 интеграция
- `beeline/` - Beeline телефония
- `gs_api/` - Google Sheets API
- `robokassa/` - платежная система

### Telegram бот (`telegram_bot/`)
- `handlers/` - обработчики сообщений
- `helpers/` - вспомогательные функции

### Данные (`data/`)
- `models.py` - модели базы данных
- `server_models.py` - API модели

### Конфигурация (`config/`)
- `config.py` - основные настройки
- `const.py` - константы

## Технологический стек

### Backend
- Python 3.10
- FastAPI
- PostgreSQL
- Supervisor

### API и Интеграции
- AssemblyAI API
- Google Sheets API
- AmoCRM API
- Битрикс24 API
- Robokassa API

### Клиенты
- Telegram Bot API
- Web API (FastAPI)