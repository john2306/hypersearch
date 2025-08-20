#!/usr/bin/env python3
"""
HyperSearch Performance Monitor
Monitors system performance, database health, and Celery workers
"""

import asyncio
import logging
import time
import psutil
import asyncpg
from datetime import datetime, timedelta
from typing import Dict, Any
import httpx

from settings import DB_DSN
from core.db import AsyncPGORM, init_db_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HyperSearch-Monitor")


class PerformanceMonitor:
    """System and application performance monitor"""

    def __init__(self):
        self.orm: AsyncPGORM | None = None
        self.start_time = time.time()

    async def initialize(self):
        """Initialize database connection"""
        try:
            await init_db_pool(DB_DSN, min_size=1, max_size=3)
            self.orm = AsyncPGORM()
            logger.info("✅ Monitor initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize monitor: {e}")
            raise

    def get_system_metrics(self) -> Dict[str, Any]:
        """Get system performance metrics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return {
                "timestamp": datetime.now().isoformat(),
                "uptime": time.time() - self.start_time,
                "cpu": {
                    "percent": cpu_percent,
                    "count": psutil.cpu_count(),
                    "load_avg": psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                    "used": memory.used
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent
                },
                "network": dict(psutil.net_io_counters()._asdict()) if psutil.net_io_counters() else {}
            }
        except Exception as e:
            logger.error(f"Error getting system metrics: {e}")
            return {"error": str(e)}

    async def get_database_metrics(self) -> Dict[str, Any]:
        """Get database performance metrics"""
        if not self.orm:
            return {"error": "Database not initialized"}

        try:
            # Connection stats
            connection_stats = await self.orm.fetch("""
                SELECT
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections
                FROM pg_stat_activity
                WHERE datname = current_database()
            """)

            # Table stats
            knowledge_stats = await self.orm.fetch("""
                SELECT
                    COUNT(*) as total_records,
                    COUNT(*) FILTER (WHERE status = 'COMPLETED') as completed,
                    COUNT(*) FILTER (WHERE status = 'PROCESSING') as processing,
                    COUNT(*) FILTER (WHERE status = 'QUEUED') as queued,
                    COUNT(*) FILTER (WHERE status = 'FAILED') as failed
                FROM knowledge
            """)

            chunk_stats = await self.orm.fetch("""
                SELECT
                    COUNT(*) as total_chunks,
                    AVG(length(raw_text)) as avg_text_length,
                    MAX(length(raw_text)) as max_text_length
                FROM chunks
            """)

            # Recent activity (last hour)
            recent_activity = await self.orm.fetch("""
                SELECT
                    COUNT(*) as recent_knowledge,
                    COUNT(DISTINCT knowledge_id) as recent_chunks_knowledge
                FROM knowledge k
                LEFT JOIN chunks c ON k.id = c.knowledge_id
                WHERE k.created_at > NOW() - INTERVAL '1 hour'
            """)

            return {
                "timestamp": datetime.now().isoformat(),
                "connections": connection_stats[0] if connection_stats else {},
                "knowledge": knowledge_stats[0] if knowledge_stats else {},
                "chunks": chunk_stats[0] if chunk_stats else {},
                "recent_activity": recent_activity[0] if recent_activity else {}
            }

        except Exception as e:
            logger.error(f"Error getting database metrics: {e}")
            return {"error": str(e)}

    async def check_api_health(self, url: str = "http://localhost:8000") -> Dict[str, Any]:
        """Check API health"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                start_time = time.time()
                response = await client.get(f"{url}/health")
                response_time = time.time() - start_time

                return {
                    "timestamp": datetime.now().isoformat(),
                    "status_code": response.status_code,
                    "response_time": response_time,
                    "healthy": response.status_code == 200,
                    "response": response.json() if response.status_code == 200 else None
                }
        except Exception as e:
            logger.error(f"Error checking API health: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "healthy": False,
                "error": str(e)
            }

    def check_celery_workers(self) -> Dict[str, Any]:
        """Check Celery worker processes"""
        try:
            celery_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_percent']):
                try:
                    if proc.info['cmdline'] and any('celery' in arg for arg in proc.info['cmdline']):
                        celery_processes.append({
                            "pid": proc.info['pid'],
                            "name": proc.info['name'],
                            "cmdline": ' '.join(proc.info['cmdline']),
                            "cpu_percent": proc.info['cpu_percent'],
                            "memory_percent": proc.info['memory_percent']
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return {
                "timestamp": datetime.now().isoformat(),
                "worker_count": len(celery_processes),
                "workers": celery_processes
            }
        except Exception as e:
            logger.error(f"Error checking Celery workers: {e}")
            return {"error": str(e)}

    async def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive monitoring report"""
        logger.info("Generating performance report...")

        report = {
            "report_time": datetime.now().isoformat(),
            "system": self.get_system_metrics(),
            "database": await self.get_database_metrics(),
            "api": await self.check_api_health(),
            "celery": self.check_celery_workers()
        }

        # Add health summary
        health_issues = []

        if report["system"].get("cpu", {}).get("percent", 0) > 80:
            health_issues.append("High CPU usage")

        if report["system"].get("memory", {}).get("percent", 0) > 85:
            health_issues.append("High memory usage")

        if report["system"].get("disk", {}).get("percent", 0) > 90:
            health_issues.append("High disk usage")

        if not report["api"].get("healthy", False):
            health_issues.append("API unhealthy")

        if report["celery"].get("worker_count", 0) == 0:
            health_issues.append("No Celery workers running")

        report["health_summary"] = {
            "overall_healthy": len(health_issues) == 0,
            "issues": health_issues,
            "issue_count": len(health_issues)
        }

        return report

    async def continuous_monitor(self, interval: int = 30):
        """Run continuous monitoring"""
        logger.info(f"Starting continuous monitoring (interval: {interval}s)")

        while True:
            try:
                report = await self.generate_report()

                # Log critical issues
                if not report["health_summary"]["overall_healthy"]:
                    logger.warning(f"Health issues detected: {report['health_summary']['issues']}")

                # Log key metrics
                system = report["system"]
                db = report["database"]
                logger.info(
                    f"Status: CPU={system.get('cpu', {}).get('percent', 0):.1f}% "
                    f"MEM={system.get('memory', {}).get('percent', 0):.1f}% "
                    f"Knowledge={db.get('knowledge', {}).get('total_records', 0)} "
                    f"Chunks={db.get('chunks', {}).get('total_chunks', 0)} "
                    f"Workers={report['celery'].get('worker_count', 0)}"
                )

                await asyncio.sleep(interval)

            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(interval)


async def main():
    """Main monitoring function"""
    monitor = PerformanceMonitor()
    await monitor.initialize()

    # Generate single report or start continuous monitoring
    import sys
    if "--continuous" in sys.argv:
        interval = 30
        if "--interval" in sys.argv:
            try:
                interval = int(sys.argv[sys.argv.index("--interval") + 1])
            except (IndexError, ValueError):
                interval = 30
        await monitor.continuous_monitor(interval)
    else:
        report = await monitor.generate_report()
        print("\n" + "="*50)
        print("HYPERSEARCH PERFORMANCE REPORT")
        print("="*50)
        print(f"Report Time: {report['report_time']}")
        print(f"Overall Health: {'✅ HEALTHY' if report['health_summary']['overall_healthy'] else '❌ ISSUES DETECTED'}")

        if report['health_summary']['issues']:
            print(f"Issues: {', '.join(report['health_summary']['issues'])}")

        print(f"\nSystem: CPU={report['system'].get('cpu', {}).get('percent', 0):.1f}% Memory={report['system'].get('memory', {}).get('percent', 0):.1f}%")
        print(f"Database: {report['database'].get('knowledge', {}).get('total_records', 0)} knowledge items, {report['database'].get('chunks', {}).get('total_chunks', 0)} chunks")
        print(f"API: {'✅ Healthy' if report['api'].get('healthy') else '❌ Unhealthy'}")
        print(f"Celery: {report['celery'].get('worker_count', 0)} workers")
        print("="*50)


if __name__ == "__main__":
    asyncio.run(main())
