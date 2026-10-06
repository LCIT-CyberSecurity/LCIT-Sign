from __future__ import annotations

import ipaddress
import socket

# Administrators legitimately point LCIT Sign at internal hosts (an SMTP
# relay on a private network), so private ranges are allowed. What an
# admin-supplied host must never reach is the cloud metadata endpoint,
# link-local space, the unspecified/multicast addresses, or a service port
# that has nothing to do with mail (spec §83): the connectivity test would
# otherwise be a port scanner for anything the API container can route to.
_FORBIDDEN_PORTS = frozenset(
    {20, 21, 22, 23, 53, 80, 110, 111, 135, 139, 389, 443, 445, 1433, 2049, 2375, 2376,
     3306, 3389, 5432, 5900, 6379, 8080, 9200, 11211, 27017}
)


class OutboundTargetError(ValueError):
    pass


def _forbidden(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or address.is_reserved
    )


def validate_outbound_target(
    host: str, port: int, *, allow_ports: frozenset[int] = frozenset()
) -> None:
    """Raise OutboundTargetError unless `host:port` is an acceptable
    admin-configured mail target. Resolves the name, so a hostname that
    points at a forbidden address is caught too."""
    host = host.strip()
    if not host or any(c.isspace() or c in "/@?#" for c in host):
        raise OutboundTargetError("invalid host")
    if not 1 <= port <= 65535 or (port in _FORBIDDEN_PORTS and port not in allow_ports):
        raise OutboundTargetError(f"port {port} is not allowed")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # Unresolvable hosts are reported by the connection diagnostics
        # (DNS step), not rejected here.
        return
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if _forbidden(address):
            raise OutboundTargetError(f"address {address} is not allowed")
