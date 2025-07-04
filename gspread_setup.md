
# Настройка доступа к Google Таблице

1. Перейдите на https://console.cloud.google.com/
2. Создайте проект и включите Google Sheets API и Google Drive API.
3. Создайте сервисный аккаунт, выдайте ему роль Editor.
4. Скачайте JSON-файл ключей и загрузите его в проект как `credentials.json`.
5. Поделитесь вашей Google Таблицей с email из JSON-файла (например: `my-bot@my-project.iam.gserviceaccount.com`).
