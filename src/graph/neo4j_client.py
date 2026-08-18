from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase, ManagedTransaction, Session

# Load .env file
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

_driver = None
_connection_verified = False


def get_driver():
    """
    Get or initialize the Neo4j GraphDatabase driver.
    Verifies connection on first use and raises clear errors if connectivity fails.
    """
    global _driver, _connection_verified

    if _driver is None:
        try:
            _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        except Exception as exc:
            raise RuntimeError(
                f"Failed to create Neo4j driver with URI={NEO4J_URI}, user={NEO4J_USER}: {exc}"
            ) from exc

    # Verify connectivity on first use
    if not _connection_verified:
        try:
            with _driver.session() as session:
                session.run("RETURN 1")
            _connection_verified = True
        except Exception as exc:
            raise RuntimeError(
                f"Cannot connect to Neo4j at {NEO4J_URI} with user={NEO4J_USER}. "
                f"Check DB is running and credentials are correct. Error: {exc}"
            ) from exc

    return _driver


def run_query(query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Run a Cypher query and return results.
    
    Args:
        query: Cypher query string
        parameters: Query parameters (optional)
    
    Returns:
        List of result records as dicts
    """
    driver = get_driver()
    with driver.session() as session:
        result = session.run(query, parameters or {})
        return [record.data() for record in result]


def close_driver():
    """Close the Neo4j driver connection."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
