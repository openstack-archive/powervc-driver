# Copyright 2013 IBM Corp.
import unittest
import mox

from nova.openstack.common import gettextutils
gettextutils.install('nova')

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

        # Create an instance of Mox
        self.moxer = mox.Mox()

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
        Utils.__init__ = init_utils
        Utils.get_local_staging_project_id = fake_get_id
        Utils.get_local_staging_user_id = fake_get_user_id

        self.PowerVCCloudManager = PowerVCCloudManager()

    def tearDown(self):
        pass

    def test_translate_pvc_instance(self):

        pvc_instance = self.pvcinstance.pvc_instance
        ctx = self.ctx

        self.moxer.StubOutWithMock(self.PowerVCCloudManager._staging_cache,
                                   "get_staging_user_and_project")
        self.PowerVCCloudManager._staging_cache.\
            get_staging_user_and_project(True)\
            .AndReturn(('', ''))
        self.moxer.StubOutWithMock(self.PowerVCCloudManager,
                                   "_get_image_from_instance")
        self.PowerVCCloudManager._get_image_from_instance(ctx,
                                                          pvc_instance,
                                                          None)\
            .AndReturn(self.osimage.os_image)

        self.moxer.StubOutWithMock(self.PowerVCCloudManager,
                                   "_get_flavor_from_instance")
        self.PowerVCCloudManager._get_flavor_from_instance(ctx,
                                                           pvc_instance,
                                                           None)\
            .AndReturn(self.osflavor.os_flavor)

        self.moxer.StubOutWithMock(flavors, "save_flavor_info")
        flavors.save_flavor_info(dict(), self.osflavor.os_flavor)\
            .AndReturn("system_metadata")

        self.moxer.StubOutWithMock(self.PowerVCCloudManager,
                                   "_get_instance_root_device_name")

        self.PowerVCCloudManager._get_instance_root_device_name(pvc_instance,
                                                                None)\
            .AndReturn("/dev/sda")

        self.moxer.ReplayAll()

        ins, image, flavor = self.PowerVCCloudManager.\
            _translate_pvc_instance(ctx, pvc_instance)

        self.moxer.UnsetStubs()
        self.moxer.VerifyAll()

        print "====ins======================================================="
        print ins
        print "===self.osinstance.os_instance================================"
        print self.osinstance.os_instance
        print "=============================================================="

        self.assertEqual(ins, self.osinstance.os_instance)
