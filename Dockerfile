FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD python manage.py collectstatic --noinput && gunicorn -w 4 -b 0.0.0.0:8000 --timeout 300 --access-logfile - --error-logfile - ServerOpor.wsgi:application
