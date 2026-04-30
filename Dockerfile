# Use a lightweight Python image as our foundation
FROM python:3.11-slim

# Set the working directory inside the cloud container
WORKDIR /app

# Copy the requirements file first to optimize the build speed
COPY requirements.txt .

# Install all the necessary libraries (FastAPI, Supabase, LangChain, etc.)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code (main.py, prompts.py, .env) into the container
COPY . .

# Tell AWS to run the app on port 8080
EXPOSE 8080

# The command to start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]