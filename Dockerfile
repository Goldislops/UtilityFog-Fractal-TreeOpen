
# UtilityFog-Fractal-TreeOpen Container
# Minimal container for visualization demo

FROM python:3.11-slim

LABEL org.opencontainers.image.title="UtilityFog Fractal Tree"
LABEL org.opencontainers.image.description="Fractal tree coordination system with visualization"
LABEL org.opencontainers.image.source="https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen"
LABEL org.opencontainers.image.licenses="MIT"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY testing_requirements.txt .
RUN pip install --no-cache-dir -r testing_requirements.txt

# Copy application code
COPY . .

# Install the package in development mode
RUN pip install -e .

# Create non-root user
RUN useradd --create-home --shell /bin/bash ufog
RUN chown -R ufog:ufog /app
USER ufog

# Expose port for visualization server
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import utilityfog_frontend.cli_viz.cli; print('OK')" || exit 1

# Default command - run visualization demo
CMD ["python", "-m", "utilityfog_frontend.cli_viz.cli", "--demo", "--port", "8080", "--host", "0.0.0.0"]
