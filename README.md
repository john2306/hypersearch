# � HyperSearch - High-Performance Semantic Search Engine

HyperSearch is a high-performance semantic search and knowledge processing service built with FastAPI, Celery, and PostgreSQL with vector extensions. It provides efficient document processing, embedding generation, and hybrid search capabilities.

## ✨ Features

- **High-Performance Architecture**: Optimized for concurrent processing with async/await
- **Hybrid Search**: Combines full-text search (BM25) with semantic search (embeddings)
- **Scalable Processing**: Celery-based background task processing with optimized batching
- **Monitoring & Health Checks**: Built-in performance monitoring and health endpoints
- **Production Ready**: Optimized database connections, error handling, and retry logic
- **Vector Database**: PostgreSQL with pgvector for efficient similarity search

## 🛠️ Technology Stack

- **FastAPI**: High-performance web framework
- **Celery**: Distributed task queue for background processing
- **PostgreSQL + pgvector**: Vector database for embeddings
- **OpenAI**: Embedding generation and text processing
- **AsyncPG**: High-performance PostgreSQL driver
- **Redis/RabbitMQ**: Message broker for Celery

## 📋 Prerequisites

- Python 3.10+
- PostgreSQL with vector extensions (paradedb recommended)
- Redis or RabbitMQ
- OpenAI API key

## 🚀 Quick Start

### 1. Environment Setup

```bash
# Clone and enter directory
cd hypersearch

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env
```

### 2. Database Setup

Start PostgreSQL with vector extensions:

```bash
docker run --name paradedb \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=hyperdb \
  -v paradedb_data:/var/lib/postgresql/data/ \
  -p 5400:5432 -d \
  paradedb/paradedb:latest
```

### 3. Message Broker Setup

Choose Redis (recommended) or RabbitMQ:

```bash
# Redis
docker run -d --rm --name redis-stack \
  -p 6379:6379 -p 8001:8001 \
  redis/redis-stack:latest

# OR RabbitMQ
docker run -d --rm --name rabbitmq \
  -p 5672:5672 -p 15672:15672 \
  rabbitmq:3.13-management
```

### 4. Start Services

Use the optimized startup script:

```bash
# Start all services (API + Celery workers + monitoring)
./start.sh start

# Or start individual components
./start.sh api-only     # Just the API
./start.sh celery-only  # Just Celery workers
./start.sh dev          # Development mode

# Check status
./start.sh status

# View performance metrics
./start.sh monitor
```

### 5. Initialize Database

```bash
# Initialize database schema
curl -X GET "http://localhost:8000/init_db"
```

## 📊 API Endpoints

### Health & Monitoring
- `GET /health` - Comprehensive health check
- `GET /metrics` - System and application metrics
- `GET /docs` - Interactive API documentation

### Knowledge Management
- `POST /add_knowledge` - Add knowledge items for processing
- `GET /knowledge/status/{id}` - Get processing status
- `GET /knowledge/stats` - Get processing statistics

### Database Management
- `GET /init_db` - Initialize database schema
- `GET /clear_db` - Clear all data (development only)

## 🔧 Performance Optimizations

### Database
- **Connection Pooling**: Optimized asyncpg pool (5-20 connections)
- **Retry Logic**: Automatic retry with exponential backoff
- **Batch Processing**: Efficient bulk operations
- **Indexed Queries**: Optimized indexes for fast searches

### Celery Workers
- **Thread Pool**: I/O optimized for async operations
- **Controlled Concurrency**: Batch processing with size limits
- **Memory Management**: Automatic worker recycling
- **Error Handling**: Comprehensive retry and error recovery

### API Server
- **Async/Await**: Non-blocking request handling
- **Request Validation**: Pydantic models with validation
- **CORS Optimization**: Efficient middleware configuration
- **Health Monitoring**: Real-time health and metrics

## 📈 Monitoring

### Built-in Monitoring
```bash
# Real-time monitoring
python monitor.py --continuous --interval 30

# One-time report
python monitor.py
```

### Key Metrics
- System resources (CPU, memory, disk)
- Database performance and connection stats
- Celery worker status and task processing
- API response times and health status

## 🔧 Configuration

### Environment Variables
```bash
# Required
OPENAI_API_KEY=your_api_key
PG_HOST=localhost
PG_PASSWORD=your_password
BROKER_URL=redis://localhost:6379/0

# Performance Tuning
CELERY_CONCURRENCY=4
DB_POOL_MAX_SIZE=20
MAX_BATCH_SIZE=1000

# Monitoring
ENABLE_MONITORING=true
LOG_LEVEL=INFO
```

### Production Deployment
```bash
# Production mode with monitoring
ENABLE_MONITORING=true ./start.sh start

# Custom worker concurrency
CELERY_CONCURRENCY=8 ./start.sh start
```

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI       │    │     Celery      │    │   PostgreSQL    │
│   Web Server    │◄──►│    Workers      │◄──►│   + pgvector    │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     Client      │    │     Redis/      │    │    OpenAI       │
│   Applications  │    │   RabbitMQ      │    │      API        │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 📚 Data Model

### Knowledge Table
- Stores source documents with metadata
- Tracks processing status (QUEUED → PROCESSING → COMPLETED)
- Supports upserts based on source_id

### Chunks Table
- Stores processed text fragments
- Contains both raw and processed text
- Includes 1536-dimensional embeddings for semantic search
- Linked to knowledge via foreign key

## 🐛 Troubleshooting

### Common Issues

1. **Loop Attachment Error**: Fixed with improved async handling
2. **Database Connection Issues**: Automatic retry logic implemented
3. **Memory Issues**: Worker recycling and batch size limits
4. **Rate Limiting**: Exponential backoff for OpenAI API

### Debugging
```bash
# Check service status
./start.sh status

# View logs
tail -f hypersearch.log

# Monitor performance
python monitor.py

# Test individual components
curl http://localhost:8000/health
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## ⚙️ Database Schema

### Extensions Required

```sql
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector for embeddings
CREATE EXTENSION IF NOT EXISTS pg_search;  -- BM25 full-text search
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- UUID generation