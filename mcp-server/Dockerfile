# Skælvox VM Evolver MCP Server
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir mcp

# Copy application code
COPY *.py ./
COPY mcp-server/ ./mcp-server/

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the MCP server
CMD ["python", "mcp-server/server.py"]
