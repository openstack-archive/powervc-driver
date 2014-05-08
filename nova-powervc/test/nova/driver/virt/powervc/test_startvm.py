COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

import unittest
import mox
from powervc.nova.driver.virt.powervc.service import PowerVCService
from test.fake_pvc_instance import FakePVCInstance
from test.fake_os_instance import FakeOSInstance
from novaclient.v1_1 import servers


class TestStartVM(unittest.TestCase):

    def setUp(self):
        """
        The method "setUp" is used to initialize the fake environment
        """
        self.moxer = mox.Mox()
        fake_instance = FakePVCInstance().pvc_instance

        self.os_instance = FakeOSInstance().os_instance

        def init(self, pvc_client=None):
            self._client = None
            self._api = None

        PowerVCService.__init__ = init

        self.service = PowerVCService()

        self.manager = servers.ServerManager(self)

        self.server = \
            servers.Server(self.manager, fake_instance)

    def tearDown(self):
        pass

    def runTest(self):

        self.moxer.StubOutWithMock(self.service, "_get_server")
        self.service._get_server(self.os_instance).AndReturn(self.server)

        self.moxer.StubOutWithMock(self.service, "_get_pvcserver")
        self.service._get_pvcserver(self.server).AndReturn(self.server)

        self.moxer.ReplayAll()

        self.service.power_on(self.os_instance)

        print "Test should log VM is out of sync because status is 'ACTIVE'"

        self.moxer.UnsetStubs()
        self.moxer.VerifyAll()
