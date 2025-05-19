import unittest
from unittest.mock import Mock, patch

from telegram_bot.handlers.on_msg import audio_handler
from telegram_bot.helpers import txt


class TestAudioHandler(unittest.TestCase):

    @patch("pyrogram.Client")
    @patch("pyrogram.types.Message")
    def test_send_error_if_no_db_user(self, mock_message, mock_client):
        mock_message.from_user.id = 12345  # ID, который, предположим, не существует в базе
        mock_client.send_message = Mock()  # Мокаем метод отправки сообщения

        # Мокаем вызов к базе данных так, чтобы он всегда возвращал None
        with patch("data.models.User.get_or_none", return_value=None):
            audio_handler(mock_client, mock_message)

        # Проверяем, что метод send_message вызывался с ожидаемыми аргументами
        mock_client.send_message.assert_called_once_with(12345, txt.error_no_db_user)


if __name__ == '__main__':
    unittest.main()
