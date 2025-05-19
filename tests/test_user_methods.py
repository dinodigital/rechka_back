import unittest

import peewee

from data.models import User, Mode

# Создаем тестовую базу данных в памяти (быстрее и не оставляет файлов на диске)
TEST_DB = peewee.SqliteDatabase(':memory:')


class TestUserMethods(unittest.TestCase):

    def setUp(self):
        # Связываем наши модели с тестовой базой данных и создаем таблицы
        self.db = TEST_DB
        self.db.bind([User, Mode], bind_refs=False, bind_backrefs=False)
        self.db.connect()
        self.db.create_tables([User, Mode])

        # Создаем пользователя для тестирования с начальным балансом в 100 секунд
        self.user = User.create(tg_id=12345, seconds_balance=180)

    def test_minus_seconds_balance(self):
        # Разговор на 50 секунд. Обновляем баланс.
        # Минимальная величина для изменения баланса равна 60 секундам,
        # поэтому отнимается 60, а не 50.
        self.user.minus_seconds_balance(50)
        self.assertEqual(self.user.seconds_balance, 120)

        # Уменьшаем баланс на еще 30 секунд и проверяем результат
        self.user.minus_seconds_balance(30)
        self.assertEqual(self.user.seconds_balance, 60)

        self.user.seconds_balance = 100

    def test_add_seconds_balance(self):
        # Добавляем баланс на 50 секунд и проверяем результат
        # Минимальная величина для изменения баланса равна 60 секундам,
        # поэтому прибавляется 60, а не 50.
        self.user.add_seconds_balance(50)
        self.assertEqual(self.user.seconds_balance, 240)

        # Увеличиваем баланс на еще 30 секунд и проверяем результат
        self.user.add_seconds_balance(30)
        self.assertEqual(self.user.seconds_balance, 300)

        self.user.add_seconds_balance(90)
        self.assertEqual(self.user.seconds_balance, 390)

        self.user.seconds_balance = 100

    def tearDown(self):
        # Закрыть соединение с базой данных и удалить таблицы после тестирования
        self.db.drop_tables([User, Mode])
        self.db.close()


if __name__ == '__main__':
    unittest.main()
