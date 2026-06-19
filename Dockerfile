# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Graphviz for SVG generation
RUN apt-get update && apt-get install -y --no-install-recommends graphviz && rm -rf /var/lib/apt/lists/*

# Copy server code
COPY sse_server.py .
COPY lca_server.py .
COPY lca_engine.py .
COPY lca_svg_engine.py .
COPY lca_svg.py .
COPY case_studies/ ./case_studies/

# Expose port 9000
EXPOSE 9000

# Set environment variable for port
ENV PORT=9000

# Run the server
CMD ["python", "sse_server.py"]
