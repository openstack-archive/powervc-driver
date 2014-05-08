COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

import unittest
import mox

from powervc.nova.driver.virt.powervc.sync import flavorsync
import powervc.common.config as cfg

CONF = cfg.CONF


class TestFlavorSync(unittest.TestCase):

    def setUp(self):
        """
        The method "setUp" is used to initialize the fake environment
        """

        # Create an instance of Mox
        self.moxer = mox.Mox()

        def init(self, driver=None):
            self.driver = None
            self.prefix = 'PVC-'

        flavorsync.FlavorSync.__init__ = init

        self.flavor_sync = flavorsync.FlavorSync(driver=None)

    def tearDown(self):
        pass

    def runTest(self):

        flavor_black_list = []
        flavor_white_list = []

        self.moxer.StubOutWithMock(self.flavor_sync, "get_flavors_black_list")
        self.flavor_sync.get_flavors_black_list().AndReturn(flavor_black_list)

        self.moxer.StubOutWithMock(self.flavor_sync, "get_flavors_white_list")
        self.flavor_sync.get_flavors_white_list().AndReturn(flavor_white_list)

        self.moxer.ReplayAll()

        response = self.flavor_sync._check_for_sync("m1.tiny")

        self.assertTrue(response, msg=None)

        flavor_black_list = ["m1.tiny", "m1.small"]
        flavor_white_list = ["m1.tiny", "m1.medium"]

        flavor_name_list = ["m1.tiny", "m1.small", "m1.medium", "m1.large"]
        response_list = [False, False, True, False]

        for (flavor_name, response) in zip(flavor_name_list, response_list):

            self.moxer.UnsetStubs()

            self.moxer.StubOutWithMock(self.flavor_sync,
                                       "get_flavors_black_list")
            self.flavor_sync.get_flavors_black_list().\
                AndReturn(flavor_black_list)

            self.moxer.StubOutWithMock(self.flavor_sync,
                                       "get_flavors_white_list")
            self.flavor_sync.get_flavors_white_list().\
                AndReturn(flavor_white_list)
            self.moxer.ReplayAll()

            response_ret = self.flavor_sync._check_for_sync(flavor_name)

            self.assertEquals(response_ret, response)

        self.moxer.UnsetStubs()
