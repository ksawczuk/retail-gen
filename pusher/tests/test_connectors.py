"""Unit tests for pusher.connectors: direct and tunnelled connections, against a fake connection factory."""

import unittest

from pusher.config import ProxyAddress
from pusher.connectors import DirectConnector, TunnelConnector
from pusher.tests.fakes import make_factory

HOST = "example.cloud.databricks.com"
PROXY = ProxyAddress("pusher-proxy", 3128)


class DirectConnectorTest(unittest.TestCase):
    """The direct connector opens the workspace host and sets no tunnel."""

    def test_opens_the_workspace_host_with_no_tunnel(self):
        """One connection to the host, with the timeout, and no CONNECT target."""
        factory, _ = make_factory([])
        DirectConnector(factory).open(HOST, 30)
        self.assertEqual(factory.opened, [{"host": HOST, "port": None, "timeout": 30, "tunnel": None}])


class TunnelConnectorTest(unittest.TestCase):
    """The tunnel connector opens the proxy and tells it to tunnel to the workspace host."""

    def test_opens_the_proxy_and_tunnels_to_the_workspace_on_443(self):
        """The connection goes to the proxy's host and port; the tunnel target is the workspace on 443."""
        factory, _ = make_factory([])
        TunnelConnector(PROXY, factory).open(HOST, 30)
        self.assertEqual(
            factory.opened, [{"host": "pusher-proxy", "port": 3128, "timeout": 30, "tunnel": (HOST, 443)}])

    def test_a_workspace_host_with_a_port_keeps_its_port(self):
        """A host given as name:port tunnels to that port."""
        factory, _ = make_factory([])
        TunnelConnector(PROXY, factory).open(f"{HOST}:8443", 30)
        self.assertEqual(factory.opened[0]["tunnel"], (HOST, 8443))

    def test_each_open_is_a_new_connection(self):
        """Two opens give two connections, each with its own tunnel setting."""
        factory, _ = make_factory([])
        connector = TunnelConnector(PROXY, factory)
        connector.open(HOST, 30)
        connector.open(HOST, 30)
        self.assertEqual(len(factory.opened), 2)


if __name__ == "__main__":
    unittest.main()
