# =================================================================
# Licensed Materials - Property of IBM
#
# (c) Copyright IBM Corp. 2014 All Rights Reserved
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
# ====================================l=============================
from webob import exc

from novaclient.openstack.common import gettextutils
from mock import MagicMock

_ = gettextutils._

from novaclient import exceptions
from novaclient.tests.fixture_data import client
from novaclient.tests.fixture_data import hypervisors as data
from novaclient.tests import utils
from hostmaintenanceclient.v1_1 import host_maintenance


class HostMaintenanceTest(utils.FixturedTestCase):
    client_fixture_class = client.V1
    data_fixture_class = data.V1

    def compare_to_expected(self, expected, hyper):
        for key, value in expected.items():
            self.assertEqual(getattr(hyper, key), value)

    def test_host_maintenance_get(self):
        restAPI = MagicMock()
        args = MagicMock()
        # generate cs parameter
        get_return_value = {"maintenance_status": "on",
                            "maintenance_migration_action": "none"}

        host_manager = host_maintenance.HostMaintenanceManager(restAPI)
        host_manager.api.client.get = MagicMock(
            return_value=(200, get_return_value))
        self.cs.host_maintenance = host_manager
        args.set_status = None
        args.migrate = None
        args.target_host = None
        args.host = "789522X_067E30B"

        # generate args parameter
        host_maintenance.do_host_maintenance(self.cs, args)
        restAPI.client.get.assert_called_once_with(
            '/os-host-maintenance-mode/789522X_067E30B')

    def test_host_maintenance_get_not_found(self):
        restAPI = MagicMock()
        args = MagicMock()
        # generate cs parameter
        host_manager = host_maintenance.HostMaintenanceManager(restAPI)
        host_manager.api.client.get = MagicMock(
            side_effect=exc.HTTPNotFound('The specified host cannot be found'))
        self.cs.host_maintenance = host_manager
        args.set_status = None
        args.migrate = None
        args.target_host = None
        args.host = "789522X_067E30B"

        # generate args parameter
        self.assertRaises(exc.HTTPNotFound,
                          host_maintenance.do_host_maintenance,
                          self.cs, args)
        restAPI.client.get.assert_called_once_with(
            '/os-host-maintenance-mode/789522X_067E30B')

    def test_host_maintenance_update_enable_success(self):
        restAPI = MagicMock()
        args = MagicMock()
        # generate cs parameter
        update_return_value = {"hypervisor_maintenance":
                               {"status": "enable",
                                "migrate": "none",
                                "target-host": "none",
                                "hypervisor_hostname": "789522X_067E30B"}
                               }

        host_manager = host_maintenance.HostMaintenanceManager(restAPI)
        host_manager.api.client.put = MagicMock(
            return_value=(200, update_return_value))
        self.cs.host_maintenance = host_manager
        args.set_status = 'enable'
        args.migrate = None
        args.target_host = None
        args.host = "789522X_067E30B"

        # generate args parameter
        host_maintenance.do_host_maintenance(self.cs, args)
        restAPI.client.put.assert_called_once_with(
            '/os-host-maintenance-mode/789522X_067E30B',
            body={'status': 'enable', 'migrate': None, 'target_host': None})

    def test_host_maintenance_update_disable_success(self):
        restAPI = MagicMock()
        args = MagicMock()
        # generate cs parameter
        update_return_value = {"hypervisor_maintenance":
                               {"status": "disable",
                                "migrate": "none",
                                "target-host": "none",
                                "hypervisor_hostname": "789522X_067E30B"}
                               }

        host_manager = host_maintenance.HostMaintenanceManager(restAPI)
        host_manager.api.client.put = MagicMock(
            return_value=(200, update_return_value))
        self.cs.host_maintenance = host_manager
        args.set_status = 'disable'
        args.migrate = None
        args.target_host = None
        args.host = "789522X_067E30B"

        # generate args parameter
        host_maintenance.do_host_maintenance(self.cs, args)
        restAPI.client.put.assert_called_once_with(
            '/os-host-maintenance-mode/789522X_067E30B',
            body={'status': 'disable'})

    def test_host_maintenance_get_parameter_error1(self):
        args = MagicMock()
        args.set_status = None
        args.migrate = 'active-only'
        args.target_host = None
        args.host = "789522X_067E30B"

        self.assertRaises(exceptions.CommandError,
                          host_maintenance.do_host_maintenance, self.cs, args)

    def test_host_maintenance_get_parameter_error2(self):
        args = MagicMock()
        args.set_status = None
        args.migrate = None
        args.target_host = "789522X_067E31B"
        args.host = "789522X_067E30B"

        self.assertRaises(exceptions.CommandError,
                          host_maintenance.do_host_maintenance, self.cs, args)

    def test_host_maintenance_get_parameter_error3(self):
        args = MagicMock()
        args.set_status = 'disable'
        args.migrate = None
        args.target_host = "789522X_067E31B"
        args.host = "789522X_067E30B"

        self.assertRaises(exceptions.CommandError,
                          host_maintenance.do_host_maintenance, self.cs, args)
