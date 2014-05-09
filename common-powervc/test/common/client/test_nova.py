# Copyright 2013 IBM Corp.
import unittest
from mock import MagicMock
from mock import patch
import novaclient.tests.v1_1.test_servers as servers_testbox
import novaclient.tests.v1_1.test_flavors as flavors_testbox
import novaclient.tests.v1_1.test_hypervisors as hypervisors_testbox
from novaclient.tests.v1_1 import fakes
from novaclient.v1_1 import servers
from novaclient.v1_1 import flavors
from novaclient.tests import utils
from powervc.common.client.extensions import nova as ext_nova
from powervc.common.client import delegate
from powervc.common import utils as comm_utils

"""
    This class similarly extend the current nova client test cases
    and also provided are examples of how someone can override and existing
    method in the event we need to test something unique to powerVC.

    The current methods that are overridden expect the same results as the base
    class test cases and are only provided for example.

    For specific PowerVC data model, just override the parent fake data
    structure and corresponding testcase methods logic that could verify
    the functions.

    To run the testcases, alternatively:
    1. Right click the TestNovaClient.py --> Run As --> Python unit-test
    or
    2. Refer to this link for detail UT running information:
    https://jazz04.rchland.ibm.com:9443/jazz/service/ +
    com.ibm.team.workitem.common.internal.rest.IAttachmentRestService/ +
    itemName/com.ibm.team.workitem.Attachment/67843

    All the testcases should be run successfully.
"""


class PVCFakeClient(fakes.FakeClient):
    """
        This PVCFakeClient class extends the current nova FakeClient,
        aiming to set the self.client variable to PVCFakeHTTPClient
    """
    def __init__(self, *args, **kwargs):
        fakes.FakeClient.__init__(self, *args, **kwargs)
        self.client = PVCFakeHTTPClient(**kwargs)


class PVCFakeHTTPClient(fakes.FakeHTTPClient):
    """
        This PVCFakeHTTPClient class extends the current nova FakeHTTPClient.
        For all the HTTP requests in this class, it returns a fake json data
        as specified beforehand instead of requesting to a real environment.
    """
    def __init__(self, **kwargs):
        fakes.FakeHTTPClient.__init__(self, **kwargs)

    def get_servers(self, **kw):
        """
            Override the parent method to a new powerVC specified server.
        """
        return (200, {}, {"servers": [
            {'id': 1234, 'name': 'sample-server'},
            {'id': 5678, 'name': 'powerVC sample-server'}
        ]})

    def get_servers_detail(self, **kw):
        """
            Override the parent method to specify powerVC specified server
            detail.
        """
        return (200, {}, {"servers": [
            {
                "id": 1234,
                "name": "sample-server",
                "image": {
                    "id": 2,
                    "name": "sample image",
                },
                "flavor": {
                    "id": 1,
                    "name": "256 MB Server",
                },
                "hostId": "e4d909c290d0fb1ca068ffaddf22cbd0",
                "status": "BUILD",
                "progress": 60,
                "addresses": {
                    "public": [{
                        "version": 4,
                        "addr": "1.2.3.4",
                    }, {
                        "version": 4,
                        "addr": "5.6.7.8",
                    }],
                    "private": [{
                        "version": 4,
                        "addr": "10.11.12.13",
                    }],
                },
                "metadata": {
                    "Server Label": "Web Head 1",
                    "Image Version": "2.1"
                },
                "OS-EXT-SRV-ATTR:host": "computenode1",
                "security_groups": [{
                    'id': 1, 'name': 'securitygroup1',
                    'description': 'FAKE_SECURITY_GROUP',
                    'tenant_id': '4ffc664c198e435e9853f2538fbcd7a7'
                }],
                "OS-EXT-MOD:some_thing": "mod_some_thing_value"},
            {
                "id": 5678,
                "name": "powerVC sample-server",
                "image": {
                    "id": 2,
                    "name": "sample image",
                },
                "flavor": {
                    "id": 1,
                    "name": "256 MB Server",
                },
                "hostId": "9e107d9d372bb6826bd81d3542a419d6",
                "status": "ACTIVE",
                "addresses": {
                    "public": [{
                        "version": 4,
                        "addr": "4.5.6.7",
                    }, {
                        "version": 4,
                        "addr": "5.6.9.8",
                    }],
                    "private": [{
                        "version": 4,
                        "addr": "10.13.12.13",
                    }],
                },
                "metadata": {
                    "Server Label": "DB 1"
                },
                "OS-EXT-SRV-ATTR:host": "computenode2",
            },
            {
                "id": 9012,
                "name": "sample-server3",
                "image": "",
                "flavor": {
                    "id": 1,
                    "name": "256 MB Server",
                },
                "hostId": "9e107d9d372bb6826bd81d3542a419d6",
                "status": "ACTIVE",
                "addresses": {
                    "public": [{
                        "version": 4,
                        "addr": "4.5.6.7",
                    }, {
                        "version": 4,
                        "addr": "5.6.9.8",
                    }],
                    "private": [{
                        "version": 4,
                        "addr": "10.13.12.13",
                    }],
                },
                "metadata": {
                    "Server Label": "DB 1"
                }
            }
        ]})

    def get_flavors_detail(self, **kw):
        """
            Override the parent method to specify powerVC specified flavors
            detail.
        """
        return (200, {}, {'flavors': [
            {'id': 1, 'name': '256 MB Server', 'ram': 256, 'disk': 10,
             'OS-FLV-EXT-DATA:ephemeral': 10,
             'os-flavor-access:is_public': True,
             'links': {}},
            {'id': 2, 'name': '128 MB Server', 'ram': 512, 'disk': 0,
             'OS-FLV-EXT-DATA:ephemeral': 20,
             'os-flavor-access:is_public': False,
             'links': {}},
            {'id': 'aa1', 'name': 'PowerVC 128 MB Server', 'ram': 5120,
             'disk': 5678, 'OS-FLV-EXT-DATA:ephemeral': 0,
             'os-flavor-access:is_public': True,
             'links': {}}
        ]})

    def get_os_hypervisors(self, **kw):
        """
            Override the parent method to specify powerVC specified hypervisors
            detail.
        """
        return (200, {}, {"hypervisors": [
                {'id': 1234, 'hypervisor_hostname': 'hyper1'},
                {'id': 5678, 'hypervisor_hostname': 'hyper2'},
                ]})

    def get_storage_connectivity_groups_f4b541cb_f418_4b4b_83b9_a8148650d4e9(
            self, **kw):
        """
        To get a fake detail storage_connectivity_group
        """
        return (200, {}, {"storage_connectivity_group":
                {
                    "auto_add_vios": True,
                    "fc_storage_access": True,
                    "display_name": "Auto-SCG for Registered SAN",
                    "host_list": [
                        {
                            "name": "ngp01_02_vios_1",
                            "vios_list": [
                                {
                                    "lpar_id": 1,
                                    "name": "10-F715A",
                                    "id": "ngp01_02_vios_1##1"
                                }
                            ]
                        },
                        {
                            "name": "ngp01_03_vios_1",
                            "vios_list": [
                                {
                                    "lpar_id": 1,
                                    "name": "10-F76CA",
                                    "id": "ngp01_03_vios_1##1"
                                }
                            ]
                        }
                    ],
                    "created_at": "2013-08-23 14:56:11.787465",
                    "enabled": True,
                    "auto_defined": True,
                    "id": "f4b541cb-f418-4b4b-83b9-a8148650d4e9"
                }})

    def get_storage_connectivity_groups(self, **kw):
        """
        To return a fake storage_connectivity_groups
        """
        return (200, {}, {"storage_connectivity_groups": [
                {
                    "display_name": "Auto-SCG for Registered SAN",
                    "id": "f4b541cb-f418-4b4b-83b9-a8148650d4e9"
                },
                {
                    "display_name": "SCG sample",
                    "id": "sdfb541cb-f418-4b4b-3129-a814865023fs"
                }]})

    def get_storage_connectivity_groups_detail(self, **kw):
        """
        To return a fake detail storage_connectivity_groups
        """
        return (200, {}, {"storage_connectivity_groups": [
            {
                "auto_add_vios": True,
                "fc_storage_access": True,
                "display_name": "Auto-SCG for Registered SAN",
                "host_list": [
                    {
                        "name": "ngp01_02_vios_1",
                        "vios_list": [
                            {
                                "lpar_id": 1,
                                "name": "10-F715A",
                                "id": "ngp01_02_vios_1##1"
                            }
                        ]
                    },
                    {
                        "name": "ngp01_03_vios_1",
                        "vios_list": [
                            {
                                "lpar_id": 1,
                                "name": "10-F76CA",
                                "id": "ngp01_03_vios_1##1"
                            }
                        ]
                    }
                ],
                "created_at": "2013-08-23 14:56:11.787465",
                "enabled": True,
                "auto_defined": True,
                "id": "f4b541cb-f418-4b4b-83b9-a8148650d4e9"},
            {
                "auto_add_vios": True,
                "fc_storage_access": True,
                "display_name": "SCG Sample",
                "host_list": [
                    {
                        "name": "ngp01_02_vios_1",
                        "vios_list": [
                            {
                                "lpar_id": 1,
                                "name": "10-F715A",
                                "id": "ngp01_02_vios_1##1"
                            }
                        ]
                    }, {
                        "name": "ngp01_03_vios_1",
                        "vios_list": [
                            {
                                "lpar_id": 1,
                                "name": "10-F76CA",
                                "id": "ngp01_03_vios_1##1"
                            }
                        ]
                    }
                ],
                "created_at": "2013-08-23 14:56:11.787465",
                "enabled": True,
                "auto_defined": True,
                "id": "sdfb541cb-f418-4b4b-3129-a814865023fs"
            }
        ]})


class PVCNovaServersTest(servers_testbox.ServersTest):
    """
        This PVCNovaServersTest class extends the current nova
        ServersTest class to provide servers related UT cases.
    """

    def setUp(self):
        super(PVCNovaServersTest, self).setUp()
        nova_fakeclient = PVCFakeClient('r', 'p', 's',
                                        'http://localhost:5000/')
        # delegate to nova extension class
        nova_client = delegate.new_composite_deletgate(
            [ext_nova.Client(nova_fakeclient), nova_fakeclient])

        self.cs = nova_client

    def tearDown(self):
        super(PVCNovaServersTest, self).tearDown()

    def test_list(self):
        comm_utils.get_utils = MagicMock()
        comm_utils.get_utils().get_multi_scg_accessible_servers = MagicMock()
        self.cs.manager.list()
        comm_utils.get_utils().get_multi_scg_accessible_servers.\
            assert_called_once_with(None, None, True, None)

    def test_list_servers(self):
        """
            Override this method to test listing powerVC server
            Here is the same logic as OpenStack for example.
        """
        sl = self.cs.manager.list_all_servers()
        print sl
        self.cs.assert_called('GET', '/servers/detail')
        [self.assertTrue(isinstance(s, servers.Server)) for s in sl]

    def test_list_instance_storage_viable_hosts(self):
        with patch('novaclient.base.getid') as mock:
            mock.return_value = 'server_id'
            mock('server')
            self.cs.manager.api.client.get = MagicMock(
                return_value=('head', 'body'))
            ret = self.cs.manager.list_instance_storage_viable_hosts('server')
            self.cs.manager.api.client.get.assert_called_once_with(
                '/storage-viable-hosts?instance_uuid=server_id')
            self.assertEqual(ret, 'body')


class PVCNovaFlavorsTest(flavors_testbox.FlavorsTest):
    """
        This PVCNovaFlavorsTest class extends the current nova
        FlavorsTest class to provide flavors related UT cases.
    """

    def setUp(self):
        super(PVCNovaFlavorsTest, self).setUp()
        nova_fakeclient = PVCFakeClient('r', 'p', 's',
                                        'http://localhost:5000/')
        # delegate to nova extension class
        nova_client = delegate.new_composite_deletgate(
            [ext_nova.Client(nova_fakeclient), nova_fakeclient])

        self.cs = nova_client

    def tearDown(self):
        super(PVCNovaFlavorsTest, self).tearDown()

    def test_get_flavor_details_alphanum_id(self):
        """
            Override this method to test list specified powerVC
            flavors. Here is the same logic as OpenStack for example.
        """
        f = self.cs.flavors.get('aa1')
        self.cs.assert_called('GET', '/flavors/aa1')
        self.assertTrue(isinstance(f, flavors.Flavor))
        # Verify the preset value
        self.assertEqual(f.ram, 5120)
        self.assertEqual(f.disk, 5678)
        self.assertEqual(f.ephemeral, 0)
        self.assertEqual(f.is_public, True)


class PVCNovaHypervisorsTest(hypervisors_testbox.HypervisorsTest):
    """
        This PVCNovaHypervisorsTest class extends the current nova
        HypervisorsTest class to provide hypervisors related UT cases.
    """

    def setUp(self):
        super(PVCNovaHypervisorsTest, self).setUp()
        nova_fakeclient = PVCFakeClient('r', 'p', 's',
                                        'http://localhost:5000/')
        # delegate to nova extension class
        nova_client = delegate.new_composite_deletgate(
            [ext_nova.Client(nova_fakeclient), nova_fakeclient])

        self.cs = nova_client

    def tearDown(self):
        super(PVCNovaHypervisorsTest, self).tearDown()

    def test_hypervisor_detail(self):
        """
            Override this method to test if listing powerVC hypervisors
            function works.
            Here is the same logic as OpenStack for example.
        """
        expected = [
            dict(id=1234,
                 service=dict(id=1, host='compute1'),
                 vcpus=4,
                 memory_mb=10 * 1024,
                 local_gb=250,
                 vcpus_used=2,
                 memory_mb_used=5 * 1024,
                 local_gb_used=125,
                 hypervisor_type="xen",
                 hypervisor_version=3,
                 hypervisor_hostname="hyper1",
                 free_ram_mb=5 * 1024,
                 free_disk_gb=125,
                 current_workload=2,
                 running_vms=2,
                 cpu_info='cpu_info',
                 disk_available_least=100),
            dict(id=2,
                 service=dict(id=2, host="compute2"),
                 vcpus=4,
                 memory_mb=10 * 1024,
                 local_gb=250,
                 vcpus_used=2,
                 memory_mb_used=5 * 1024,
                 local_gb_used=125,
                 hypervisor_type="xen",
                 hypervisor_version=3,
                 hypervisor_hostname="hyper2",
                 free_ram_mb=5 * 1024,
                 free_disk_gb=125,
                 current_workload=2,
                 running_vms=2,
                 cpu_info='cpu_info',
                 disk_available_least=100)]

        result = self.cs.hypervisors.list()
        print result
        self.cs.assert_called('GET', '/os-hypervisors/detail')

        for idx, hyper in enumerate(result):
            self.compare_to_expected(expected[idx], hyper)


class PVCSCGTest(utils.TestCase):
    def setUp(self):
        super(PVCSCGTest, self).setUp()
        nova_fakeclient = PVCFakeClient('r', 'p', 's',
                                        'http://localhost:5000/')
        # delegate to nova extension class
        nova_client = delegate.new_composite_deletgate(
            [ext_nova.Client(nova_fakeclient), nova_fakeclient])

        self.cs = nova_client

    def compare_to_expected(self, expected, hyper):
        for key, value in expected.items():
            self.assertEqual(getattr(hyper, key), value)

    def test_get_detail_SCGs(self):
        expected = [
            dict(id="f4b541cb-f418-4b4b-83b9-a8148650d4e9",
                 auto_add_vios=True,
                 fc_storage_access=True,
                 display_name="Auto-SCG for Registered SAN",
                 enabled=True,
                 auto_defined=True),
            dict(id="sdfb541cb-f418-4b4b-3129-a814865023fs",
                 auto_add_vios=True,
                 fc_storage_access=True,
                 display_name="SCG Sample",
                 enabled=True,
                 auto_defined=True)]

        result = self.cs.storage_connectivity_groups.list()
        self.cs.assert_called('GET', '/storage-connectivity-groups/detail')

        for idx, hyper in enumerate(result):
            self.compare_to_expected(expected[idx], hyper)

    def test_get_SCGs(self):
        expected = dict(id="f4b541cb-f418-4b4b-83b9-a8148650d4e9",
                        auto_add_vios=True,
                        fc_storage_access=True,
                        display_name="Auto-SCG for Registered SAN",
                        enabled=True,
                        auto_defined=True)

        result = self.cs.storage_connectivity_groups.\
            get('f4b541cb-f418-4b4b-83b9-a8148650d4e9')
        self.cs.assert_called('GET',
                              '/storage-connectivity-groups/' +
                              'f4b541cb-f418-4b4b-83b9-a8148650d4e9')

        self.compare_to_expected(expected, result)


class SCGImageManagerTest(unittest.TestCase):
    def setUp(self):
        super(SCGImageManagerTest, self).setUp()
        nova_fakeclient = PVCFakeClient('r', 'p', 's',
                                        'http://localhost:5000/')
        # delegate to nova extension class
        nova_client = delegate.new_composite_deletgate(
            [ext_nova.Client(nova_fakeclient), nova_fakeclient])

        self.cs = nova_client

    def test_list(self):
        with patch('novaclient.base.Manager._list') as mock:
            mock.return_value = ['image1', 'image2', 'image3']
            ret = self.cs.scg_images.list('scgUUID')
            mock.assert_called_once_with(
                '/storage-connectivity-groups/scgUUID/images', 'images')
            self.assertEqual(ret, ['image1', 'image2', 'image3'])

    def test_list_ids(self):
        class FakeImage(object):
            def __init__(self, image_id):
                self.id = image_id

        self.cs.scg_images.list = MagicMock(
            return_value=[FakeImage(1), FakeImage(2), FakeImage(3)])
        ret = self.cs.scg_images.list_ids('scgUUID')
        self.assertEqual(ret, [1, 2, 3])
