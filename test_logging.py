#!/usr/bin/env python3
"""Test script for request logging functionality"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from utils.request_logger import RequestLogger

def test_request_logger():
    """Test the request logger functionality"""
    print("Testing Request Logger...")
    
    # Initialize logger
    logger = RequestLogger("test_requests.db")
    
    # Test logging successful request
    request_id = logger.log_request(
        model="gpt-3.5-turbo",
        provider="openai",
        status="success",
        latency_ms=250,
        tokens_prompt=100,
        tokens_completion=200,
        tokens_total=300,
        client_ip="127.0.0.1"
    )
    print(f"Logged successful request: #{request_id}")
    
    # Test logging failed request
    request_id = logger.log_request(
        model="gpt-4",
        provider="azure",
        status="fail",
        latency_ms=500,
        error_message="Timeout error",
        client_ip="192.168.1.100"
    )
    print(f"Logged failed request: #{request_id}")
    
    # Test getting recent logs
    recent_logs = logger.get_recent(10)
    print(f"Recent logs count: {len(recent_logs)}")
    
    # Test getting stats
    stats = logger.get_stats(hours=1)
    print(f"Stats: {stats}")
    
    # Test provider stats
    provider_stats = logger.get_provider_stats(hours=1)
    print(f"Provider stats: {provider_stats}")
    
    # Test model stats
    model_stats = logger.get_model_stats(hours=1)
    print(f"Model stats: {model_stats}")
    
    print("All tests passed!")
    
    # Clean up test database
    import os
    if os.path.exists("test_requests.db"):
        os.remove("test_requests.db")

if __name__ == "__main__":
    test_request_logger()