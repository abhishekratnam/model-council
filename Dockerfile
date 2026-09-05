FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code (main.py, app/, static/)
COPY . .

# Expose the port the app runs on
EXPOSE 8787

# Run the application using the root main.py
# We set MODEL_COUNCIL_ALLOW_NETWORK=1 so the app allows binding to 0.0.0.0
ENV MODEL_COUNCIL_ALLOW_NETWORK=1
CMD ["python", "main.py"]