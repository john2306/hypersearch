#!/usr/bin/env python3
"""
HyperSearch Test Suite
Tests the optimized HyperSearch API and processing pipeline
"""

import asyncio
import httpx
import time
import json
from typing import List, Dict, Any

# Test configuration
API_BASE_URL = "http://localhost:8000"
TEST_TIMEOUT = 30.0

# Sample test data
SAMPLE_KNOWLEDGE = [
    {
        "source_id": "test_001",
        "title": "Introduction to Machine Learning",
        "body": "Machine learning is a subset of artificial intelligence that focuses on algorithms that can learn from data without being explicitly programmed.",
        "content_type": "article",
        "metadata": {"category": "AI", "difficulty": "beginner"}
    },
    {
        "source_id": "test_002",
        "title": "Deep Learning Fundamentals",
        "body": "Deep learning uses neural networks with multiple layers to model and understand complex patterns in data.",
        "content_type": "tutorial",
        "metadata": {"category": "AI", "difficulty": "intermediate"}
    },
    {
        "source_id": "test_003",
        "title": "Natural Language Processing",
        "body": "NLP is a field of AI that helps computers understand, interpret and manipulate human language.",
        "content_type": "guide",
        "metadata": {"category": "NLP", "difficulty": "advanced"}
    }
]


class HyperSearchTester:
    """Test suite for HyperSearch API"""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=TEST_TIMEOUT)
        self.test_results = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    def log_test(self, test_name: str, success: bool, details: str = "", duration: float = 0):
        """Log test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name} ({duration:.2f}s)")
        if details:
            print(f"    {details}")

        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details,
            "duration": duration
        })

    async def test_health_check(self):
        """Test API health endpoint"""
        start_time = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/health")
            duration = time.time() - start_time

            if response.status_code == 200:
                health_data = response.json()
                services_healthy = all(
                    service != "error" for service in health_data.get("services", {}).values()
                )
                self.log_test(
                    "Health Check",
                    services_healthy,
                    f"Status: {health_data.get('status', 'unknown')}",
                    duration
                )
                return services_healthy
            else:
                self.log_test(
                    "Health Check",
                    False,
                    f"HTTP {response.status_code}",
                    duration
                )
                return False
        except Exception as e:
            duration = time.time() - start_time
            self.log_test("Health Check", False, str(e), duration)
            return False

    async def test_metrics_endpoint(self):
        """Test metrics endpoint"""
        start_time = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/metrics")
            duration = time.time() - start_time

            if response.status_code == 200:
                metrics_data = response.json()
                has_system_metrics = "system" in metrics_data
                self.log_test(
                    "Metrics Endpoint",
                    has_system_metrics,
                    f"Uptime: {metrics_data.get('uptime', 0):.1f}s",
                    duration
                )
                return has_system_metrics
            else:
                self.log_test(
                    "Metrics Endpoint",
                    False,
                    f"HTTP {response.status_code}",
                    duration
                )
                return False
        except Exception as e:
            duration = time.time() - start_time
            self.log_test("Metrics Endpoint", False, str(e), duration)
            return False

    async def test_database_init(self):
        """Test database initialization"""
        start_time = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/init_db")
            duration = time.time() - start_time

            success = response.status_code == 200
            details = response.json().get("status", "unknown") if success else f"HTTP {response.status_code}"

            self.log_test("Database Init", success, details, duration)
            return success
        except Exception as e:
            duration = time.time() - start_time
            self.log_test("Database Init", False, str(e), duration)
            return False

    async def test_add_knowledge(self):
        """Test adding knowledge items"""
        start_time = time.time()
        try:
            response = await self.client.post(
                f"{self.base_url}/add_knowledge",
                json=SAMPLE_KNOWLEDGE
            )
            duration = time.time() - start_time

            if response.status_code == 200:
                result = response.json()
                knowledge_ids = result.get("knowledge_ids", [])
                batches_queued = result.get("batches_queued", 0)

                success = len(knowledge_ids) == len(SAMPLE_KNOWLEDGE)
                details = f"Added {len(knowledge_ids)} items, {batches_queued} batches queued"

                self.log_test("Add Knowledge", success, details, duration)
                return knowledge_ids if success else []
            else:
                self.log_test(
                    "Add Knowledge",
                    False,
                    f"HTTP {response.status_code}: {response.text}",
                    duration
                )
                return []
        except Exception as e:
            duration = time.time() - start_time
            self.log_test("Add Knowledge", False, str(e), duration)
            return []

    async def test_knowledge_status(self, knowledge_ids: List[int]):
        """Test knowledge status endpoint"""
        if not knowledge_ids:
            self.log_test("Knowledge Status", False, "No knowledge IDs to test")
            return False

        start_time = time.time()
        try:
            # Test first knowledge item
            knowledge_id = knowledge_ids[0]
            response = await self.client.get(f"{self.base_url}/knowledge/status/{knowledge_id}")
            duration = time.time() - start_time

            if response.status_code == 200:
                status_data = response.json()
                has_required_fields = all(
                    field in status_data for field in ["id", "source_id", "status", "title"]
                )

                self.log_test(
                    "Knowledge Status",
                    has_required_fields,
                    f"Status: {status_data.get('status', 'unknown')}",
                    duration
                )
                return has_required_fields
            else:
                self.log_test(
                    "Knowledge Status",
                    False,
                    f"HTTP {response.status_code}",
                    duration
                )
                return False
        except Exception as e:
            duration = time.time() - start_time
            self.log_test("Knowledge Status", False, str(e), duration)
            return False

    async def test_knowledge_stats(self):
        """Test knowledge statistics endpoint"""
        start_time = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/knowledge/stats")
            duration = time.time() - start_time

            if response.status_code == 200:
                stats_data = response.json()
                has_stats = "status_breakdown" in stats_data and "total_chunks" in stats_data

                total_records = sum(stats_data.get("status_breakdown", {}).values())
                details = f"Total records: {total_records}, Chunks: {stats_data.get('total_chunks', 0)}"

                self.log_test("Knowledge Stats", has_stats, details, duration)
                return has_stats
            else:
                self.log_test(
                    "Knowledge Stats",
                    False,
                    f"HTTP {response.status_code}",
                    duration
                )
                return False
        except Exception as e:
            duration = time.time() - start_time
            self.log_test("Knowledge Stats", False, str(e), duration)
            return False

    async def wait_for_processing(self, knowledge_ids: List[int], max_wait: int = 60):
        """Wait for knowledge processing to complete"""
        if not knowledge_ids:
            return False

        print(f"⏳ Waiting for processing to complete (max {max_wait}s)...")
        start_time = time.time()

        while time.time() - start_time < max_wait:
            try:
                # Check first item status
                response = await self.client.get(f"{self.base_url}/knowledge/status/{knowledge_ids[0]}")
                if response.status_code == 200:
                    status_data = response.json()
                    status = status_data.get("status", "unknown")
                    chunk_count = status_data.get("chunk_count", 0)

                    print(f"   Status: {status}, Chunks: {chunk_count}")

                    if status == "COMPLETED" and chunk_count > 0:
                        duration = time.time() - start_time
                        self.log_test(
                            "Processing Wait",
                            True,
                            f"Completed with {chunk_count} chunks",
                            duration
                        )
                        return True
                    elif status == "FAILED":
                        self.log_test("Processing Wait", False, "Processing failed")
                        return False

                await asyncio.sleep(5)  # Wait 5 seconds before checking again

            except Exception as e:
                print(f"   Error checking status: {e}")
                await asyncio.sleep(5)

        self.log_test("Processing Wait", False, f"Timeout after {max_wait}s")
        return False

    def print_summary(self):
        """Print test summary"""
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        failed_tests = total_tests - passed_tests

        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests*100):.1f}%" if total_tests > 0 else "No tests run")

        if failed_tests > 0:
            print("\nFailed Tests:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  - {result['test']}: {result['details']}")

        print("="*60)

        return failed_tests == 0


async def run_tests():
    """Run complete test suite"""
    print("🧪 Starting HyperSearch Test Suite")
    print("="*60)

    async with HyperSearchTester() as tester:
        # Basic connectivity tests
        health_ok = await tester.test_health_check()
        if not health_ok:
            print("❌ Health check failed - stopping tests")
            tester.print_summary()
            return False

        await tester.test_metrics_endpoint()

        # Database tests
        await tester.test_database_init()

        # Knowledge processing tests
        knowledge_ids = await tester.test_add_knowledge()

        if knowledge_ids:
            await tester.test_knowledge_status(knowledge_ids)
            await tester.test_knowledge_stats()

            # Wait for processing (optional - comment out for faster tests)
            print("\n📝 Testing knowledge processing...")
            await tester.wait_for_processing(knowledge_ids, max_wait=120)

        # Print final summary
        return tester.print_summary()


if __name__ == "__main__":
    try:
        success = asyncio.run(run_tests())
        exit_code = 0 if success else 1
        print(f"\n🏁 Tests {'completed successfully' if success else 'failed'}")
        exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n💥 Test suite crashed: {e}")
        exit(1)
