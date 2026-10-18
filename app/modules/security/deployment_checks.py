"""Fail closed on production configurations that redirect private data off this host."""
import ipaddress
from urllib.parse import urlsplit


def local_service_host(host: str | None, service: str) -> bool:
    if host in {"localhost", service}:
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def validate_local_services(database_url: str, embedding_url: str):
    database = urlsplit(database_url)
    if not database.scheme.startswith("sqlite") and not local_service_host(database.hostname, "db"):
        raise ValueError("Production database must use the local db service or loopback address")
    embedding = urlsplit(embedding_url)
    if embedding.scheme not in {"http", "https"} or not local_service_host(embedding.hostname, "embeddings"):
        raise ValueError("Production embedding service must use the local embeddings service or loopback address")
