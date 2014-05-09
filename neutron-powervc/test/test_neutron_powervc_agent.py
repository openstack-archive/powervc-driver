# Copyright 2013 IBM Corp.

"""
Test methods in PowerVCNeutronAgent
"""
import unittest
import mock
import sys

# import these modules to patch
import powervc.common.client
import powervc.neutron.api
import powervc.neutron.client
import powervc.neutron.db

# use them to pass pep8
powervc.common.client
powervc.neutron.api
powervc.neutron.client
powervc.neutron.db

# patch work
client_module = sys.modules['powervc.common.client']
client_module.factory = mock.MagicMock()

api_module = sys.modules['powervc.neutron.api']
api_module.powervc_rpc = mock.MagicMock()

neutron = sys.modules['powervc.neutron.client']
neutron.local_os_bindings = mock.MagicMock()
neutron.powervc_bindings = mock.MagicMock()

db = sys.modules['powervc.neutron.db']
db.powervc_db_v2 = mock.MagicMock()


from powervc.neutron.agent.neutron_powervc_agent import PowerVCNeutronAgent
from powervc.neutron.common import constants


class port:
    def __init__(self):
        pass

    def get(self, key):
        pass


class TestPowerVCNeutronAgent(unittest.TestCase):
    def setUp(self):
        super(TestPowerVCNeutronAgent, self).setUp()
        PowerVCNeutronAgent._setup_rpc = mock.MagicMock
        self.powervc_neutron_agent = PowerVCNeutronAgent()

    def tearDown(self):
        pass

    def test_delete_local_port_1(self):
        # contains device_owner
        db_port = mock.MagicMock()
        db_port.get = mock.MagicMock()

        local_port = mock.MagicMock()
        local_port.get = mock.MagicMock(
                                    return_value="network:router_interface")

        self.powervc_neutron_agent.pvc = mock.MagicMock()
        self.powervc_neutron_agent.pvc.create_port = mock.MagicMock()

        self.powervc_neutron_agent._delete_local_port(local_port, db_port)
        self.powervc_neutron_agent.pvc.create_port.assert_called_once_with(
            local_port)

    def test_delete_local_port_2(self):
        # 1) 3) 5)
        db_port = mock.MagicMock()
        db_port.get = mock.MagicMock(return_value=1)

        local_port = mock.MagicMock()
        local_port.get = mock.MagicMock(return_value=1)

        self.powervc_neutron_agent.local = mock.MagicMock()
        self.powervc_neutron_agent.local.delete_port = mock.MagicMock()

        self.powervc_neutron_agent._delete_local_port(local_port, db_port)
        self.powervc_neutron_agent.local.delete_port.assert_called_once_with(1)

    def test_ports_valid_1(self):
        # 2 ports, one creating, one active, return true
        port = mock.MagicMock()
        port.get = mock.MagicMock(side_effect=[1, 2])
        port_list = [port, port]

        local_port = mock.MagicMock()
        local_port.get = mock.MagicMock(
                            side_effect=[constants.STATUS_CREATING,
                                         constants.STATUS_ACTIVE])
        self.powervc_neutron_agent.db = mock.MagicMock()
        self.powervc_neutron_agent.db.get_port = mock.MagicMock(
            return_value=local_port)

        self.powervc_neutron_agent.local = mock.MagicMock()
        self.powervc_neutron_agent.local.get_port = mock.MagicMock(
            return_value=None)
        self.assertTrue(self.powervc_neutron_agent._ports_valid(port_list))

    def test_ports_valid_2(self):
        # 2 ports, both creating, return false
        port = mock.MagicMock()
        port.get = mock.MagicMock(side_effect=[1, 2])
        port_list = [port, port]

        local_port = mock.MagicMock()
        local_port.get = mock.MagicMock(
                            side_effect=[constants.STATUS_CREATING,
                                         constants.STATUS_CREATING])
        self.powervc_neutron_agent.db = mock.MagicMock()
        self.powervc_neutron_agent.db.get_port = mock.MagicMock(
            return_value=local_port)

        self.powervc_neutron_agent.local = mock.MagicMock()
        self.powervc_neutron_agent.local.get_port = mock.MagicMock(
            return_value=None)
        self.assertFalse(self.powervc_neutron_agent._ports_valid(port_list))
