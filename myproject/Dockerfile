# Use official Python 3.13 image
FROM python:3.13

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \ 
    PYTHONUNBUFFERED=1

# Set container port
EXPOSE 8000

# Install dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Create application directory
WORKDIR /app

# Copy application code
COPY . /app/

# Create non-root user and set permissions
RUN adduser --disabled-password --gecos "" --uid 5678 appuser && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app

# Switch to non-root user
USER appuser

# Verified command from your test
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "myproject.wsgi:application"]