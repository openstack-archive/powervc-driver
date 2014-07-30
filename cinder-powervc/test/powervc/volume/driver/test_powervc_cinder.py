# Copyright 2013 IBM Corp.
# mock module
import mock
import sys
import stubout
import unittest

sys.modules['powervc.common.client'] = mock.MagicMock()
# import _
from cinder.openstack.common import gettextutils
gettextutils.install('cinder')
from powervc.common import config
from cinder import exception
from cinder import db
from powervc.volume.driver.service import PowerVCService

import six


class StorageProvider():
    def __init__(self, i):
        self.free_capacity_gb = (i + 1) * 5
        self.total_capacity_gb = (i + 1) * 10


class VolumeMetadataWithPVCID():

    def __init__(self, pvc_id="1234"):
        self.key = "pvc:id"
        self.value = pvc_id


class Volume():
    def __init__(self, info):
        self._info = info
        self._add_details(info)

    def setattr(self, key, val):
        self.__setattr__(key, val)

    def _add_details(self, info):
        for (k, v) in six.iteritems(info):
            try:
                setattr(self, k, v)
            except AttributeError:
                # In this case we already defined the attribute on the class
                pass


class PowerVCDriverTestCase(unittest.TestCase):
    stubs = stubout.StubOutForTesting()

    def setUp(self):
        super(PowerVCDriverTestCase, self).setUp()

        self.stubs.Set(PowerVCService, '_client', mock.MagicMock())
        # we need mock load config file before import PowerVCDriver class
        config.parse_power_config = mock.MagicMock()
        config.CONF.log_opt_values = mock.MagicMock()
        from powervc.volume.driver.powervc import PowerVCDriver
        self.powervc_cinder_driver = PowerVCDriver()

    def test_create_volume_no_size_raise_exception(self):
        self.assertRaises(exception.InvalidVolume,
                          self.powervc_cinder_driver.create_volume,
                          None)

    def test_create_volume_succeed(self):
        # local volume passed to driver
        vol = {'id': 1234,
               'size': 1}
        volume = Volume(vol)
        # fake volume after call creating volume from pvc
        ret_vol_after_created = {'id': 4321,
                                 'status': 'creating'}
        ret_volume_after_created = Volume(ret_vol_after_created)
        # fake volume after call get volume from pvc
        ret_vol_get = {'id': 4321,
                       'status': 'available'}
        ret_volume_get = Volume(ret_vol_get)

        # mock create volume restAPI
        PowerVCService._client.volumes.create = \
            mock.MagicMock(return_value=ret_volume_after_created)
        # mock get volume restAPI
        PowerVCService._client.volumes.get = \
            mock.MagicMock(return_value=ret_volume_get)
        # mock db access operation
        db.volume_update = mock.MagicMock(return_value=None)

        dic = self.powervc_cinder_driver.create_volume(volume)
        self.assertEqual({'status': 'available',
                          'metadata': {'pvc:id': 4321}},
                         dic, "return vol doesn't match")

    def test_create_volume_failed(self):
        # local volume passed to driver
        vol = {'id': 1234,
               'size': 1}
        volume = Volume(vol)
        # fake volume after call creating volume from pvc
        ret_vol_after_created = {'id': 4321,
                                 'status': 'creating'}
        ret_volume_after_created = Volume(ret_vol_after_created)
        # fake volume after call get volume from pvc
        ret_vol_get = {'id': 4321,
                       'status': 'error'}
        ret_volume_get = Volume(ret_vol_get)

        # mock create volume restAPI
        PowerVCService._client.volumes.create = \
            mock.MagicMock(return_value=ret_volume_after_created)
        # mock get volume restAPI
        PowerVCService._client.volumes.get = \
            mock.MagicMock(return_value=ret_volume_get)
        # mock db access operation
        db.volume_update = mock.MagicMock(return_value=None)

        dic = self.powervc_cinder_driver.create_volume(volume)
        self.assertEqual({'status': 'error',
                          'metadata': {'pvc:id': 4321}},
                         dic, "return vol doesn't match")

    def test_create_volume_not_found(self):
        # local volume passed to driver
        vol = {'id': 1234,
               'size': 1}
        volume = Volume(vol)
        # fake volume after call creating volume from pvc
        ret_vol_after_created = {'id': 4321,
                                 'status': 'creating'}
        ret_volume_after_created = Volume(ret_vol_after_created)
        # fake volume after call get volume from pvc
        ret_vol_get = {'id': 4321,
                       'status': 'error'}
        ret_volume_get = Volume(ret_vol_get)

        # mock create volume restAPI
        PowerVCService._client.volumes.create = \
            mock.MagicMock(return_value=ret_volume_after_created)
        # mock get volume restAPI
        # first time raise an exception,
        # second time return a error volume
        PowerVCService._client.volumes.get = \
            mock.MagicMock(side_effect=[exception.NotFound,
                                        ret_volume_get])
        # mock db access operation
        db.volume_update = mock.MagicMock(return_value=None)

        dic = self.powervc_cinder_driver.create_volume(volume)
        self.assertEqual({'status': 'error',
                          'metadata': {'pvc:id': 4321}},
                         dic, "return vol doesn't match")

    def test_delete_volume_success(self):
        # fake volume which will be passed to driver service
        vol_info = {'id': 1234,
                    'size': 1}
        volume = Volume(vol_info)
        setattr(volume, 'volume_metadata', [VolumeMetadataWithPVCID("1234")])
        # fake existed volume
        existed_vol_info = {"status": 'available', 'id': 1234}
        existed_volume_get = Volume(existed_vol_info)

        # fake volume after delete
        after_delete_vol_info = {"status": '', 'id': 1234}
        after_delete_volume_get = Volume(after_delete_vol_info)

        # mock rest API
        PowerVCService._client.volumes.get = \
            mock.MagicMock(side_effect=[existed_volume_get,
                                        after_delete_volume_get])

        self.powervc_cinder_driver.delete_volume(volume)

    def test_delete_volume_no_powervc_attribute_error(self):
        # fake volume which will be passed to driver service
        vol_info = {'id': 1234, 'size': 1}
        volume = Volume(vol_info)
        self.assertRaises(AttributeError,
                          self.powervc_cinder_driver.delete_volume,
                          volume)

    def test_delete_volume_not_found_exception(self):
        vol_info = {'id': 1234, 'size': 1}
        volume = Volume(vol_info)
        setattr(volume, 'volume_metadata', [VolumeMetadataWithPVCID("1234")])

        PowerVCService._client.volumes.get = \
            mock.MagicMock(side_effect=exception.NotFound())

        self.assertRaises(exception.NotFound,
                          self.powervc_cinder_driver.delete_volume,
                          volume)

    def test_get_volume_stats(self):
        # fake a storage provider list
        ret_sp = [StorageProvider(i) for i in range(10)]
        # mock rest api
        PowerVCService._client.storage_providers.list = \
            mock.MagicMock(return_value=ret_sp)
        # fake a expected return dictionary
        expected_ret_dic = {}
        expected_ret_dic["volume_backend_name"] = 'powervc'
        expected_ret_dic["vendor_name"] = 'IBM'
        expected_ret_dic["driver_version"] = 1.0
        expected_ret_dic["storage_protocol"] = 'Openstack'
        expected_ret_dic['total_capacity_gb'] = 550
        expected_ret_dic['free_capacity_gb'] = 275
        expected_ret_dic['reserved_percentage'] = 0
        expected_ret_dic['QoS_support'] = False

        ret_dic = self.powervc_cinder_driver.get_volume_stats(True)

        self.assertEqual(expected_ret_dic,
                         ret_dic,
                         'return stats should be matched')
