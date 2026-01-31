"""
Tests for BatchBuilder Service

Tests cover:
- Property grouping
- Date range compression
- Payload size estimation
- Batch splitting under 10MB
- Deterministic output
- Rate plan and room type ID inclusion
"""

import pytest
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch
from dataclasses import asdict

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestBatchBuilder:
    """Tests for BatchBuilder class"""
    
    def test_group_by_property(self):
        """5 events for 2 properties should yield 2 groups"""
        from app.services.batch_builder import BatchBuilder
        
        # Create mock DB session
        db = MagicMock()
        builder = BatchBuilder(db)
        
        # Create mock events with different property IDs
        events = []
        for i in range(3):
            event = MagicMock()
            event.id = f"event-{i}"
            event.connection_id = "conn-1"
            event.unit_id = f"unit-{i}"
            # First 3 events for property A
            events.append(event)
        
        for i in range(3, 5):
            event = MagicMock()
            event.id = f"event-{i}"
            event.connection_id = "conn-2"
            event.unit_id = f"unit-{i}"
            # Last 2 events for property B
            events.append(event)
        
        # Mock connection queries to return different property IDs
        conn_a = MagicMock()
        conn_a.channex_property_id = "prop-A"
        conn_b = MagicMock()
        conn_b.channex_property_id = "prop-B"
        
        def mock_get_connection(conn_id):
            if conn_id == "conn-1":
                return conn_a
            return conn_b
        
        builder._get_connection = mock_get_connection
        
        groups = builder._group_by_property(events)
        
        assert len(groups) == 2
        assert "prop-A" in groups
        assert "prop-B" in groups
        assert len(groups["prop-A"]) == 3
        assert len(groups["prop-B"]) == 2
    
    def test_compress_date_ranges_same_value(self):
        """7 days with same rate should compress to 1 entry with date_from/date_to"""
        from app.services.batch_builder import BatchBuilder
        
        db = MagicMock()
        builder = BatchBuilder(db)
        
        # 7 consecutive days all at 100
        values = []
        start_date = date(2024, 1, 1)
        for i in range(7):
            d = start_date + timedelta(days=i)
            values.append({"date": d.isoformat(), "rate": 10000})  # 100.00 in cents
        
        compressed = builder._compress_date_ranges(values)
        
        # Should compress to single entry
        assert len(compressed) == 1
        assert compressed[0]["date_from"] == "2024-01-01"
        assert compressed[0]["date_to"] == "2024-01-07"
        assert compressed[0]["rate"] == 10000
    
    def test_compress_date_ranges_different_values(self):
        """Days with different rates should not compress together"""
        from app.services.batch_builder import BatchBuilder
        
        db = MagicMock()
        builder = BatchBuilder(db)
        
        # Pattern: [100, 100, 150, 150]
        values = [
            {"date": "2024-01-01", "rate": 10000},
            {"date": "2024-01-02", "rate": 10000},
            {"date": "2024-01-03", "rate": 15000},
            {"date": "2024-01-04", "rate": 15000},
        ]
        
        compressed = builder._compress_date_ranges(values)
        
        # Should yield 2 entries
        assert len(compressed) == 2
        assert compressed[0]["date_from"] == "2024-01-01"
        assert compressed[0]["date_to"] == "2024-01-02"
        assert compressed[0]["rate"] == 10000
        assert compressed[1]["date_from"] == "2024-01-03"
        assert compressed[1]["date_to"] == "2024-01-04"
        assert compressed[1]["rate"] == 15000
    
    def test_payload_size_estimation(self):
        """Payload size should match JSON serialization"""
        from app.services.batch_builder import BatchBuilder
        
        db = MagicMock()
        builder = BatchBuilder(db)
        
        payload = {
            "property_id": "test-property",
            "values": [
                {"date": "2024-01-01", "rate": 10000},
                {"date": "2024-01-02", "rate": 10500},
            ]
        }
        
        estimated_size = builder._estimate_payload_size(payload)
        actual_size = len(json.dumps(payload).encode('utf-8'))
        
        # Should be exact match
        assert estimated_size == actual_size
    
    def test_split_batch_under_10mb(self):
        """Small batch should not be split"""
        from app.services.batch_builder import BatchBuilder, RateBatch
        
        db = MagicMock()
        builder = BatchBuilder(db)
        
        # Create a small batch (well under 10MB)
        batch = RateBatch(
            channex_property_id="prop-1",
            rate_plan_ids=["rp-1"],
            payload={"values": [{"date": "2024-01-01", "rate": 10000}]},
            size_bytes=100,
            unit_ids=["unit-1"],
            event_ids=["event-1"]
        )
        
        result = builder._split_batch(batch, max_bytes=10_000_000)
        
        # Should not split
        assert len(result) == 1
        assert result[0] == batch
    
    def test_split_batch_over_10mb(self):
        """Large batch should be split into multiple batches"""
        from app.services.batch_builder import BatchBuilder, RateBatch
        
        db = MagicMock()
        builder = BatchBuilder(db)
        
        # Create a batch with many values that exceeds limit
        # Each day entry is roughly ~50 bytes, so 300000 entries ≈ 15MB
        values = []
        for i in range(300000):
            d = date(2024, 1, 1) + timedelta(days=i % 365)
            values.append({"date": d.isoformat(), "rate": 10000 + i})
        
        batch = RateBatch(
            channex_property_id="prop-1",
            rate_plan_ids=["rp-1"],
            payload={"values": values},
            size_bytes=len(json.dumps({"values": values})),
            unit_ids=["unit-1"],
            event_ids=["event-1"]
        )
        
        result = builder._split_batch(batch, max_bytes=10_000_000)
        
        # Should split into 2+ batches
        assert len(result) >= 2
        
        # Each batch should be under limit
        for b in result:
            assert b.size_bytes <= 10_000_000
    
    def test_deterministic_output(self):
        """Same input should always produce same output"""
        from app.services.batch_builder import BatchBuilder
        
        db = MagicMock()
        builder = BatchBuilder(db)
        
        values = [
            {"date": "2024-01-01", "rate": 10000},
            {"date": "2024-01-02", "rate": 10000},
            {"date": "2024-01-03", "rate": 15000},
        ]
        
        # Run twice
        result1 = builder._compress_date_ranges(values.copy())
        result2 = builder._compress_date_ranges(values.copy())
        
        # Should be identical
        assert json.dumps(result1, sort_keys=True) == json.dumps(result2, sort_keys=True)
    
    def test_rate_batch_includes_rate_plan_ids(self):
        """RateBatch should include all rate plan IDs"""
        from app.services.batch_builder import RateBatch
        
        batch = RateBatch(
            channex_property_id="prop-1",
            rate_plan_ids=["rp-1", "rp-2", "rp-3"],
            payload={"values": []},
            size_bytes=50,
            unit_ids=["u-1", "u-2", "u-3"],
            event_ids=["e-1", "e-2", "e-3"]
        )
        
        assert len(batch.rate_plan_ids) == 3
        assert "rp-1" in batch.rate_plan_ids
        assert "rp-2" in batch.rate_plan_ids
        assert "rp-3" in batch.rate_plan_ids
    
    def test_availability_batch_uses_room_type_ids(self):
        """AvailabilityBatch should use room_type_ids not rate_plan_ids"""
        from app.services.batch_builder import AvailabilityBatch
        
        batch = AvailabilityBatch(
            channex_property_id="prop-1",
            room_type_ids=["rt-1", "rt-2"],
            payload={"values": []},
            size_bytes=50,
            unit_ids=["u-1", "u-2"],
            event_ids=["e-1", "e-2"]
        )
        
        assert len(batch.room_type_ids) == 2
        assert "rt-1" in batch.room_type_ids
        assert "rt-2" in batch.room_type_ids
        # Ensure it has room_type_ids attribute, not rate_plan_ids
        assert hasattr(batch, 'room_type_ids')
