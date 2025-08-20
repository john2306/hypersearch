#!/bin/bash

# HyperSearch Production Startup Script
# This script sets up the environment and starts all services with optimal settings

set -e

echo "🚀 Starting HyperSearch High-Performance Setup"
echo "=============================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if .venv exists
if [ ! -d ".venv" ]; then
    print_status "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
print_status "Activating virtual environment..."
source .venv/bin/activate

# Check Python version
PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
print_status "Python version: $PYTHON_VERSION"

# Install/upgrade dependencies
print_status "Installing/upgrading dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Set environment variables for production
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export PYTHONUNBUFFERED=1
export CELERY_OPTIMIZATION=1

# Check if required services are running
check_service() {
    local service_name=$1
    local port=$2

    if nc -z localhost $port 2>/dev/null; then
        print_status "$service_name is running on port $port"
        return 0
    else
        print_warning "$service_name is not running on port $port"
        return 1
    fi
}

# Check dependencies
print_status "Checking service dependencies..."

# Check PostgreSQL
if ! check_service "PostgreSQL" 5400; then
    print_error "PostgreSQL is not running. Please start PostgreSQL first."
    echo "Example: docker run --name paradedb -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=your_password -e POSTGRES_DB=hyperdb -v paradedb_data:/var/lib/postgresql/data/ -p 5400:5432 -d paradedb/paradedb:latest"
    exit 1
fi

# Check Redis/RabbitMQ
if ! check_service "Redis" 6379 && ! check_service "RabbitMQ" 5672; then
    print_error "Neither Redis nor RabbitMQ is running. Please start a message broker."
    echo "Redis: docker run -d --rm --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest"
    echo "RabbitMQ: docker run -d --rm --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3.13-management"
    exit 1
fi

# Get system information for optimization
CPU_CORES=$(nproc)
TOTAL_RAM=$(free -m | awk 'NR==2{printf "%.0f", $2/1024}')
RECOMMENDED_WORKERS=$((CPU_CORES * 2))

print_status "System Information:"
echo "  CPU Cores: $CPU_CORES"
echo "  Total RAM: ${TOTAL_RAM}GB"
echo "  Recommended Celery Workers: $RECOMMENDED_WORKERS"

# Function to start services
start_api() {
    print_status "Starting HyperSearch API server..."
    uvicorn main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --workers 1 \
        --loop uvloop \
        --http httptools \
        --access-log \
        --log-level info \
        --reload-delay 1 \
        &

    API_PID=$!
    echo $API_PID > .api.pid
    print_status "API server started (PID: $API_PID)"
}

start_celery() {
    print_status "Starting Celery workers..."

    # Calculate optimal concurrency
    CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-$RECOMMENDED_WORKERS}

    celery -A core worker \
        --loglevel=INFO \
        --concurrency=$CELERY_CONCURRENCY \
        --max-tasks-per-child=1000 \
        --max-memory-per-child=200000 \
        --prefetch-multiplier=1 \
        --pool=threads \
        --queues=knowledge_processing,default \
        --hostname="worker@%h" \
        &

    CELERY_PID=$!
    echo $CELERY_PID > .celery.pid
    print_status "Celery worker started (PID: $CELERY_PID, Concurrency: $CELERY_CONCURRENCY)"
}

start_monitor() {
    if [ "$ENABLE_MONITORING" = "true" ]; then
        print_status "Starting performance monitor..."
        python monitor.py --continuous --interval 60 &
        MONITOR_PID=$!
        echo $MONITOR_PID > .monitor.pid
        print_status "Monitor started (PID: $MONITOR_PID)"
    fi
}

# Function to stop services
stop_services() {
    print_status "Stopping services..."

    if [ -f .api.pid ]; then
        kill $(cat .api.pid) 2>/dev/null || true
        rm -f .api.pid
    fi

    if [ -f .celery.pid ]; then
        kill $(cat .celery.pid) 2>/dev/null || true
        rm -f .celery.pid
    fi

    if [ -f .monitor.pid ]; then
        kill $(cat .monitor.pid) 2>/dev/null || true
        rm -f .monitor.pid
    fi

    print_status "All services stopped"
}

# Handle shutdown gracefully
trap stop_services EXIT INT TERM

# Parse command line arguments
COMMAND=${1:-"start"}
ENABLE_MONITORING=${ENABLE_MONITORING:-"false"}

case $COMMAND in
    "start")
        print_status "Starting all services..."
        start_api
        sleep 3  # Wait for API to start
        start_celery
        start_monitor

        print_status "✅ HyperSearch is running!"
        echo ""
        echo "🌐 API: http://localhost:8000"
        echo "📚 Documentation: http://localhost:8000/docs"
        echo "❤️  Health Check: http://localhost:8000/health"
        echo "📊 Metrics: http://localhost:8000/metrics"
        echo ""
        print_status "Press Ctrl+C to stop all services"

        # Wait for services
        wait
        ;;

    "stop")
        stop_services
        ;;

    "restart")
        stop_services
        sleep 2
        $0 start
        ;;

    "status")
        print_status "Checking service status..."

        if [ -f .api.pid ] && kill -0 $(cat .api.pid) 2>/dev/null; then
            print_status "✅ API server is running (PID: $(cat .api.pid))"
        else
            print_warning "❌ API server is not running"
        fi

        if [ -f .celery.pid ] && kill -0 $(cat .celery.pid) 2>/dev/null; then
            print_status "✅ Celery worker is running (PID: $(cat .celery.pid))"
        else
            print_warning "❌ Celery worker is not running"
        fi

        if [ -f .monitor.pid ] && kill -0 $(cat .monitor.pid) 2>/dev/null; then
            print_status "✅ Monitor is running (PID: $(cat .monitor.pid))"
        else
            print_warning "❌ Monitor is not running"
        fi
        ;;

    "monitor")
        python monitor.py
        ;;

    "api-only")
        start_api
        print_status "✅ API server started. Press Ctrl+C to stop."
        wait
        ;;

    "celery-only")
        start_celery
        print_status "✅ Celery worker started. Press Ctrl+C to stop."
        wait
        ;;

    "dev")
        print_status "Starting in development mode..."
        uvicorn main:app --reload --port 8000 &
        API_PID=$!
        echo $API_PID > .api.pid

        celery -A core worker --loglevel=DEBUG --concurrency=2 &
        CELERY_PID=$!
        echo $CELERY_PID > .celery.pid

        print_status "Development mode started. Press Ctrl+C to stop."
        wait
        ;;

    *)
        echo "Usage: $0 {start|stop|restart|status|monitor|api-only|celery-only|dev}"
        echo ""
        echo "Commands:"
        echo "  start      - Start all services (API + Celery + Monitor)"
        echo "  stop       - Stop all services"
        echo "  restart    - Restart all services"
        echo "  status     - Check service status"
        echo "  monitor    - Run one-time performance check"
        echo "  api-only   - Start only the API server"
        echo "  celery-only - Start only Celery workers"
        echo "  dev        - Start in development mode"
        echo ""
        echo "Environment variables:"
        echo "  ENABLE_MONITORING=true  - Enable continuous monitoring"
        echo "  CELERY_CONCURRENCY=N    - Set Celery worker concurrency"
        exit 1
        ;;
esac
