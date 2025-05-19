Host Rechka-AI-TEST
  HostName 176.222.52.27
  Port 22
  User root
  IdentityFile C:\Users\kyb\.ssh\Rechka-AI-PROD

Для перезапуска служб через "supervisorctl" gitlab-runner запущен от имени "root"
nano /etc/systemd/system/gitlab-runner.service
systemctl daemon-reload
systemctl restart gitlab-runner
systemctl status gitlab-runner

CI написан под ветку test/it-psg на GitLab'е IT-PSG, она же активна на сервере
руками установлены зависимости в каталоге /root/speechka #pipenv install
файл /root/speechka/config/.env взят из каталога на тесте /home/bot/bot/okk_ai_bot/config/ далее внесены правки согласованные заказчиком
С прода 1 в 1 скопирован файл /root/speechka/config/cr.json
остановлен и отключён из автозапуска сервис nginx, т.к. занимал порт 80
настроена сборочная линия для развёртывания приложения, рестарта и просмотра логов
БД используется на yandex cloud, сделана копия ПРОД БД, но очищена таблица с интеграциями

/bin/bash
apt install -y net-tools ufw curl software-properties-common ca-certificates apt-transport-https mc
timedatectl set-timezone Europe/Moscow
localectl set-locale ru_RU.UTF-8
update-locale LANG=ru_RU.UTF-8
wget -O- https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor | tee /etc/apt/keyrings/docker.gpg > /dev/null
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable"| tee /etc/apt/sources.list.d/docker.list > /dev/null
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | bash
apt update && apt -y install docker-ce gitlab-runner
curl -L "https://github.com/docker/compose/releases/download/v2.23.3/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
usermod -aG docker gitlab-runner