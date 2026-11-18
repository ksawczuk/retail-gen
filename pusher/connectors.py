"""How the pusher reaches the workspace: straight, or through a forward proxy with a CONNECT tunnel.

Used by FilesApiClient for every request; cli.py picks the implementation once. Tests pass a fake connection factory.
"""

import http.client
from abc import ABC, abstractmethod
from urllib.parse import urlsplit

HTTPS_PORT = 443


class Connector(ABC):
    """What the client needs to start a request: a new HTTPS connection to the workspace host."""

    @abstractmethod
    def open(self, host, timeout):
        """Return a new connection that will reach `host` (a name, or name:port) over TLS."""


class DirectConnector(Connector):
    """Connects straight to the workspace host."""

    def __init__(self, connection_factory=http.client.HTTPSConnection):
        """Keep the connection factory (injected so tests need no network)."""
        self._connect = connection_factory

    def open(self, host, timeout):
        """Return an HTTPS connection to the host."""
        return self._connect(host, timeout=timeout)


class TunnelConnector(Connector):
    """Connects to the proxy, which tunnels to the workspace host (CONNECT), then speaks TLS to the workspace.

    The certificate is checked against the workspace host name, not the proxy's.
    """

    def __init__(self, proxy, connection_factory=http.client.HTTPSConnection):
        """Keep the proxy address (host and port) and the connection factory."""
        self._proxy = proxy
        self._connect = connection_factory

    def open(self, host, timeout):
        """Return a connection to the proxy that is set to tunnel to the workspace host and its port."""
        target = urlsplit(f"//{host}")
        connection = self._connect(self._proxy.host, self._proxy.port, timeout=timeout)
        connection.set_tunnel(target.hostname, target.port or HTTPS_PORT)
        return connection
