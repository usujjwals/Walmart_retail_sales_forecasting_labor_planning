FROM python:3.11-slim

WORKDIR /app

# Needed for XGBoost
RUN apt-get update && apt-get install -y \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY data/ data/
COPY scripts/ scripts/
COPY sql/ sql/

# Create folders used by the pipeline
RUN mkdir -p data/processed data/simulated

# Run backend pipeline only
CMD ["sh", "-c", "python scripts/model.py && python scripts/generated_labor_inputs.py && python scripts/load_to_mysql.py"]