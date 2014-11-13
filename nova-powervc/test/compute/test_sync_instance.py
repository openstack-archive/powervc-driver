# Copyright 2013, 2014 IBM Corp.
import unittest
import mock

from nova.i18n import _

from nova.compute import flavors

from powervc.nova.driver.compute.manager import PowerVCCloudManager
from test.fake_os_flavor import FakeOSFlavor
from test.fake_os_image import FakeOSImage
from test.fake_os_instance import FakeOSInstance
from test.fake_pvc_flavor import FakePVCFlavor
from test.fake_pvc_image import FakePVCImage
from test.fake_pvc_instance import FakePVCInstance
from test.fake_ctx import FakeCTX
from powervc.common.utils import Utils
from powervc.common.utils import StagingCache


class TestSyncInstance(unittest.TestCase):

    def setUp(self):
        """
        The method "setUp" is used to initialize the fake environment
        """

        # Create a fake OpenStack flavor object
        self.osflavor = FakeOSFlavor()
        # Create a fake OpenStack image object
        self.osimage = FakeOSImage()
        # Create a fake OpenStack instance object
        self.osinstance = FakeOSInstance()

        # Create a fake PowerVC flavor object
        self.pvcflavor = FakePVCFlavor()
        # Create a fake PowerVC image object
        self.pvcimage = FakePVCImage()
        # Create a fake PowerVC instance object
        self.pvcinstance = FakePVCInstance()

        self.ctx = FakeCTX()

        def init(self, compute_driver=None, *args, **kwargs):
            self.project_id = "ibm-default"
            self.scg_id = "storage connection group"
            self._staging_cache = StagingCache()

        def init_utils(self):
            pass

        def fake_get_id(self):
            return ""

        def fake_get_user_id(self):
            return ""

        PowerVCCloudManager.__init__ = init
        self.utils_patch = mock.patch('powervc.common.utils.Utils.__init__',
                                      init_utils)
        self.utils_patch.start()
        Utils.get_local_staging_project_id = fake_get_id
        Utils.get_local_staging_user_id = fake_get_user_id

        self.PowerVCCloudManager = PowerVCCloudManager()

    def tearDown(self):
        self.utils_patch.stop()

    def test_translate_pvc_instance(self):

        pvc_instance = self.pvcinstance.pvc_instance
        ctx = self.ctx

        self.PowerVCCloudManager._staging_cache.\
            get_staging_user_and_project = lambda x: ('', '') if x else None

        self.PowerVCCloudManager._get_image_from_instance =\
            mock.MagicMock(side_effect=[self.osimage.os_image])

        self.PowerVCCloudManager._get_flavor_from_instance =\
            mock.MagicMock(side_effect=[self.osflavor.os_flavor])

        self.PowerVCCloudManager._get_instance_root_device_name =\
            mock.MagicMock(side_effect=['/dev/sda'])

        with mock.patch('nova.compute.flavors.save_flavor_info',
                        mock.MagicMock(side_effect=['system_metadata'])):
            ins, _, _ = self.PowerVCCloudManager.\
                _translate_pvc_instance(ctx, pvc_instance)

            print "====ins==================================================="
            print ins
            print "===self.osinstance.os_instance============================"
            print self.osinstance.os_instance
            print "=========================================================="

            self.assertEqual(ins, self.osinstance.os_instance)
