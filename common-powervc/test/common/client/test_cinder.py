# Copyright 2013 IBM Corp.

from cinderclient.tests.v1 import fakes
from cinderclient.tests.v1.test_volumes import VolumesTest
from cinderclient.tests.v1.test_types import TypesTest
from cinderclient.tests import utils
from cinderclient.v1.volumes import Volume
from cinderclient.v1.volume_types import VolumeType
from cinderclient.v1.volume_types import VolumeTypeManager
from powervc.common.client.extensions import cinder as ext_cinder
from powervc.common.client import delegate
from powervc.common import utils as commonutils

import mock
import sys


"""
    This class similarly extend the current cinder client test cases
    and also provided are examples of how someone can override and existing
    method in the event we need to test something unique to powerVC.

    The current methods that are overridden expect the same results as the base
    class test cases and are only provided for example.

    For specific PowerVC data model, just override the parent fake data
    structure and corresponding testcase methods logic that could verify
    the functions.

    To run the testcases, alternatively:
    1. Right click the TestCinderClient.py --> Run As --> Python unit-test
    or
    2. Refer to this link for detail UT running information:
    https://jazz04.rchland.ibm.com:9443/jazz/service/ +
    com.ibm.team.workitem.common.internal.rest.IAttachmentRestService/ +
    itemName/com.ibm.team.workitem.Attachment/67843

    All the testcases should be run successfully.
"""


class PVCFakeClient(fakes.FakeClient):

    """
        This PVCFakeClient class extends the current cinder FakeClient,
        and pvccinderclient.CinderClient.
        aiming to set the self client variable to PVCFakeHTTPClient
    """

    def __init__(self, *args, **kwargs):
        fakes.FakeClient.__init__(self, *args, **kwargs)
        self.client = PVCFakeHTTPClient(**kwargs)
        sys.modules['powervc.common.client.factory'] = mock.MagicMock()


class PVCFakeHTTPClient(fakes.FakeHTTPClient):

    """
        This PVCFakeHTTPClient class extends the current cinder FakeHTTPClient.
        For all the HTTP requests in this class, it returns a fake json data
        as specified beforehand instead of requesting to a real environment.
        Ex, to test if json data from powerVC volume RESTAPI:
            1. Add expected powerVC volumes json raw data into
                get_volumes_detail() method
            2. Add get_volumes_{volume_id} method to return the volume
            3. Add post_volumes_{volume_id}_action to handle post logic
            4. Add testcase and new added methods will be called
    """

    def __init__(self, **kwargs):
        fakes.FakeHTTPClient.__init__(self, **kwargs)

    def get_volumes_pvcvolume(self, **kw):
        r = {'volume': self.get_volumes_detail()[2]['volumes'][1]}
        return (200, {}, r)

    def get_volumes_detail(self, **kw):
        """
            Override the parent method to a new powerVC specified volume,
            Here is the same structure as OpenStack one for example.
        """
        return (200, {}, {"volumes": [
            {'id': 1234,
             'name': 'sample-volume for cinder',
             'attachments': [{'server_id': 12234}]},
            {'id': 'pvcvolume',
             'name': 'pvc sample-volume for cinder',
             'attachments': [{'server_id': 54321}]}
        ]})

    def post_volumes_pvcvolume_action(self, body, **kw):
        """
            Add this method to handle powerVC volume post actions
            Here is the same logic as OpenStack one for example.
        """
        _body = None
        resp = 202
        assert len(list(body.keys())) == 1
        action = list(body.keys())[0]
        if action == 'os-attach':
            assert sorted(list(body[action])) == ['instance_uuid',
                                                  'mode',
                                                  'mountpoint']
        elif action == 'os-detach':
            assert body[action] is None
        elif action == 'os-reserve':
            assert body[action] is None
        elif action == 'os-unreserve':
            assert body[action] is None
        elif action == 'os-initialize_connection':
            assert list(body[action].keys()) == ['connector']
            return (202, {}, {'connection_info': 'foos'})
        elif action == 'os-terminate_connection':
            assert list(body[action].keys()) == ['connector']
        elif action == 'os-begin_detaching':
            assert body[action] is None
        elif action == 'os-roll_detaching':
            assert body[action] is None
        elif action == 'os-reset_status':
            assert 'status' in body[action]
        else:
            raise AssertionError("Unexpected action: %s" % action)
        return (resp, {}, _body)

    def get_storage_providers_2(self, **kw):
        """
        To get a fake detail storage_providers
        """
        return (200, {}, {"storage_provider":
                          {
                              "backend_type": "svc",
                              "volume_count": "null",
                              "service": {
                                  "host_display_name": "shared_v7000_1",
                                  "host": "shared_v7000_1",
                                  "id": 4
                              },
                              "backend_id": "00000200A0204C30",
                              "health_status": {
                                  "health_value": "OK"
                              },
                              "free_capacity_gb": 873.5,
                              "total_capacity_gb": 1115.5,
                              "storage_hostname": "shared_v7000_1",
                              "id": 2,
                              "backend_state": "running"
                          }})

    def get_storage_providers_detail(self, **kw):
        """
        To return a fake detail storage_providers
        """
        return (200, {}, {"storage_providers": [
            {
                "backend_type": "svc",
                "volume_count": "null",
                "service": {
                    "host_display_name": "shared_v7000_1",
                    "host": "shared_v7000_1",
                    "id": 4
                },
                "backend_id": "00000200A0204C30",
                "health_status": {
                    "health_value": "OK"
                },
                "free_capacity_gb": 873.5,
                "total_capacity_gb": 1115.5,
                "storage_hostname": "shared_v7000_1",
                "id": 2,
                "backend_state": "running"
                },
            {
                "backend_type": "fc",
                "volume_count": "null",
                "service": {
                    "host_display_name": "shared_v7000_1",
                    "host": "shared_v7000_1",
                    "id": 4
                },
                "backend_id": "00000200A0204C31",
                "health_status": {
                    "health_value": "OK"
                },
                "free_capacity_gb": 73.5,
                "total_capacity_gb": 115.5,
                "storage_hostname": "shared_v7000_2",
                "id": 3,
                "backend_state": "running"
            }
        ]})

    def get_types(self, **kw):
        return (200, {}, {
            "volume_types": [
                {
                    "extra_specs": {
                        "drivers:storage_pool": "P-NGP01-pool",
                        "capabilities:volume_backend_name": "shared_v7000_1",
                        "drivers:rsize": "-1"
                    },
                    "name": "shared_v7000_1-default",
                    "id": "6627888e-9f59-4996-8c22-5d528c3273f0"
                },
                {
                    "extra_specs": {},
                    "name": "dm-crypt",
                    "id": "a3ae95f6-4aab-4446-b1d2-0fc2f60a89bb"
                },
                {
                    "extra_specs": {},
                    "name": "LUKS",
                    "id": "291f81a2-591b-4164-b2b2-829abc935573"
                }
                ]
        })


class PVCCinderVolumesTest(VolumesTest):

    """
        This PVCCinderVolumesTest class extends the current cinder
        VolumesTest class to provide volume related UT cases.
    """

    volume_list = [
        {
            'id': 1234,
            'name': 'sample-volume for cinder',
            'attachments': [{'server_id': 12234}]},
        {
            'id': 'pvcvolume',
            'name': 'pvc sample-volume for cinder',
            'attachments': [{'server_id': 54321}]
        }]

    def setUp(self):
        super(PVCCinderVolumesTest, self).setUp()
        # get cinder client
        cinder_fakeclient = PVCFakeClient('r', 'p')
        # delegate to nova extension class
        cinder_client = delegate.new_composite_deletgate(
            [ext_cinder.Client(cinder_fakeclient), cinder_fakeclient])
        self.cs = cinder_client

    def tearDown(self):
        super(PVCCinderVolumesTest, self).tearDown()

    def test_pvcvolume_attach(self):
        """
            Add this method to test if powerVC volume attach functions
            Here is the same logic as OpenStack for example.
        """
        v = self.cs.volumes.get('pvcvolume')
        self.cs.volumes.attach(v, 1, '/dev/vdc')
        self.cs.assert_called('POST',
                              '/volumes/pvcvolume/action')

    def test_list_all_volumes(self):
        resluts = self.cs.volumes.list_all_volumes()

        self.cs.assert_called('GET', '/volumes/detail')
        self.assertEqual(resluts[0].id, 1234)
        self.assertEqual(resluts[1].name, 'pvc sample-volume for cinder')

    def test_list_volumes_1(self):
        returnvalues = [Volume(self, res, loaded=True)
                        for res in self.volume_list if res]
        commonutils.get_utils().get_multi_scg_accessible_volumes = \
            mock.MagicMock(return_value=returnvalues)
        result = self.cs.volumes.list()

        self.assertEquals(result[0].id, 1234)
        self.assertEquals(result[1].name, "pvc sample-volume for cinder")

    def test_list_volumes_2(self):
        returnvalues = [Volume(self, res, loaded=True)
                        for res in self.volume_list if res]
        commonutils.get_utils().get_scg_accessible_volumes = \
            mock.MagicMock(return_value=returnvalues)

        result = self.cs.volumes.list(True, None, 'SCGUUID', None)
        self.assertEquals(result[0].name, "sample-volume for cinder")


class PVCCinderTypesTest(TypesTest):

    """
        This PVCCinderTypesTest class extends the current cinder
        TypesTest class to provide volume Type related UT cases.
    """
    volumes_type_list = [
        {
            "extra_specs": {
                "drivers:storage_pool": "P-NGP01-pool",
                "capabilities:volume_backend_name": "shared_v7000_1",
                "drivers:rsize": "-1"
            },
            "name": "shared_v7000_1-default",
            "id": "6627888e-9f59-4996-8c22-5d528c3273f"
        },
        {
            "extra_specs": {},
            "name": "dm-crypt",
            "id": "a3ae95f6-4aab-4446-b1d2-0fc2f60a89b"
        },
        {
            "extra_specs": {},
            "name": "LUKS",
            "id": "291f81a2-591b-4164-b2b2-829abc93557"
        }]

    def setUp(self):
        super(PVCCinderTypesTest, self).setUp()
        # get cinder client
        cinder_fakeclient = PVCFakeClient('r', 'p')
        # delegate to nova extension class
        cinder_client = delegate.new_composite_deletgate(
            [ext_cinder.Client(cinder_fakeclient), cinder_fakeclient])
        self.cs = cinder_client

    def tearDown(self):
        super(PVCCinderTypesTest, self).tearDown()

    def test_list_all_storage_templates(self):

        reslut = self.cs.volume_types.list_all_storage_templates()

        self.assertEqual(reslut[0].name, "shared_v7000_1-default")

    def test_list_storage_templates_1(self):
        returnvalues = [VolumeType(VolumeTypeManager, res, loaded=True)
                        for res in self.volumes_type_list if res]

        commonutils.get_utils().get_multi_scg_accessible_storage_templates = \
            mock.MagicMock(return_value=returnvalues)
        result = self.cs.volume_types.list()

        self.assertEquals(result[0].id, "6627888e-9f59-4996-8c22-5d528c3273f")
        self.assertEquals(result[1].name, "dm-crypt")
        self.assertEquals(result[2].name, "LUKS")

    def test_list_storage_templates_2(self):
        data = self.volumes_type_list[2]
        returnvalues = [VolumeType(VolumeTypeManager, res, loaded=True)
                        for res in [data] if res]

        commonutils.get_utils().get_scg_accessible_storage_templates = \
            mock.MagicMock(return_value=returnvalues)
        result = self.cs.volume_types.list("SCGUUID", None)

        self.assertEquals(result[0].name, "LUKS")


class PVCStorageProvidersTest(utils.TestCase):

    """
    Class PVCStorageProvidersTest is used to provide
    Storage Providers related UT cases.
    """
    expected_sp = [
        dict(
            backend_type="svc",
            volume_count="null",
            service=dict(
                host_display_name="shared_v7000_1",
                host="shared_v7000_1",
                id=4),
            backend_id="00000200A0204C30",
            health_status=dict(health_value="OK"),
            free_capacity_gb=873.5,
            total_capacity_gb=1115.5,
            storage_hostname="shared_v7000_1",
            id=2,
            backend_state="running",
            storage_type="fc")]

    def setUp(self):
        super(PVCStorageProvidersTest, self).setUp()
        # get cinder client
        cinder_fakeclient = PVCFakeClient('r', 'p')
        # delegate to nova extension class
        cinder_client = delegate.new_composite_deletgate(
            [ext_cinder.Client(cinder_fakeclient), cinder_fakeclient])
        self.cs = cinder_client

    def tearDown(self):
        super(PVCStorageProvidersTest, self).tearDown()

    def compare_to_expected(self, expected, hyper):
        for key, value in expected.items():
            self.assertEqual(getattr(hyper, key), value)

    def test_get_detail_SPs(self):
        expected = [
            dict(id=2,
                 backend_type="svc",
                 backend_id="00000200A0204C30",
                 free_capacity_gb=873.5,
                 total_capacity_gb=1115.5,
                 storage_hostname="shared_v7000_1",
                 backend_state="running"),
            dict(id=3,
                 backend_type="fc",
                 backend_id="00000200A0204C31",
                 free_capacity_gb=73.5,
                 total_capacity_gb=115.5,
                 storage_hostname="shared_v7000_2",
                 backend_state="running")]

        result = self.cs.storage_providers.list_all_providers()
        self.cs.assert_called('GET', '/storage-providers/detail')

        for idx, hyper in enumerate(result):
            self.compare_to_expected(expected[idx], hyper)

    def test_get_storage_provider(self):
        expected = dict(id=2,
                        backend_type="svc",
                        backend_id="00000200A0204C30",
                        free_capacity_gb=873.5,
                        total_capacity_gb=1115.5,
                        storage_hostname="shared_v7000_1",
                        backend_state="running")

        result = self.cs.storage_providers.get(2)
        self.cs.assert_called('GET',
                              '/storage-providers/2')

        self.compare_to_expected(expected, result)

    def test_list_SP_1(self):
        expected = self.expected_sp
        returnvalue = [ext_cinder.StorageProvider(None, expected[0], True)]

        commonutils.get_utils().get_scg_accessible_storage_providers = \
            mock.MagicMock(return_value=returnvalue)
        result = self.cs.storage_providers.list(True, None, "SCGUUID", None)

        for idx, hyper in enumerate(result):
            self.compare_to_expected(expected[idx], hyper)

    def test_list_SP_2(self):
        expected = self.expected_sp
        returnvalue = [ext_cinder.StorageProvider(None, expected[0], True)]

        commonutils.get_utils().get_multi_scg_accessible_storage_providers = \
            mock.MagicMock(return_value=returnvalue)
        result = self.cs.storage_providers.list()

        for idx, hyper in enumerate(result):
            self.compare_to_expected(expected[idx], hyper)
