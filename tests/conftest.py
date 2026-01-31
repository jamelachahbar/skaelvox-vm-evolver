"""Shared fixtures for test suite."""
import sys
import os
import pytest

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
