# Base image with Python 3.13
FROM python:3.13-slim-bookworm

# Install system dependencies
# git is required for BuildTools
# wget is required for downloading BuildTools/Jars
# openjdk-17-jdk or similar is often needed for various MC versions,
# but our tool uses Java 25. Since OpenJDK 25 isn't in default repos yet,
# we'll install it as specified in our earlier tasks or use a compatible one.
# For simplicity, we'll install basic dependencies and the desired Java.

RUN apt-get update && apt-get install -y \
    wget \
    git \
    screen \
    procps \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (to interact with host docker)
RUN curl -fsSL https://get.docker.com | sh

# Install OpenJDK 25 (manually since it's very new)
# Our script currently downloads oracle-jdk@25 or expects it in a path.
# Inside a container, we'll just install it once.
RUN mkdir -p /usr/lib/jvm && \
    wget https://download.oracle.com/java/25/latest/jdk-25_linux-x64_bin.tar.gz && \
    tar -xzf jdk-25_linux-x64_bin.tar.gz -C /usr/lib/jvm && \
    rm jdk-25_linux-x64_bin.tar.gz

# Find the exact directory name created (usually jdk-25.x.x)
RUN export JAVA_HOME=$(ls -d /usr/lib/jvm/jdk-25*) && \
    ln -s "$JAVA_HOME/bin/java" /usr/bin/java && \
    ln -s "$JAVA_HOME/bin/javac" /usr/bin/javac

WORKDIR /app

# Copy requirement files first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Ensure data directory exists
RUN mkdir -p data/servers

# Expose web interface port
EXPOSE 8000

# Start command (runs webserver by default, or you can override with CLI)
CMD ["python", "webserver.py"]
