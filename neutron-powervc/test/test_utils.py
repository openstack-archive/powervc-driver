COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

import unittest
import mox

from powervc.neutron.common import utils

"""
    UT for utils functions
"""


class TestUtils(unittest.TestCase):

    def setUp(self):
        # Initialize the MOX instance
        self.moxer = mox.Mox()

    def tearDown(self):
        pass

    def test_is_network_in_white_list(self):
        self.assertTrue(self._test_case_is_network_in_white_list
                        (['*'], 'anything'))
        self.assertTrue(self._test_case_is_network_in_white_list
                        (['*'], None))
        self.assertTrue(self._test_case_is_network_in_white_list
                        (['*'], ''))
        self.assertFalse(self._test_case_is_network_in_white_list
                         (['?'], ''))
        self.assertFalse(self._test_case_is_network_in_white_list
                         ([], ''))
        self.assertFalse(self._test_case_is_network_in_white_list
                         ([], 'anything'))
        self.assertTrue(self._test_case_is_network_in_white_list
                        (['VLAN1'], 'VLAN1'))
        self.assertFalse(self._test_case_is_network_in_white_list
                         (['VLAN1'], 'VLAN'))
        self.assertFalse(self._test_case_is_network_in_white_list
                         (['VLAN1'], ''))
        self.assertFalse(self._test_case_is_network_in_white_list
                         (['VLAN1'], None))
        self.assertTrue(self._test_case_is_network_in_white_list
                        (['VLAN1', 'V2'], 'VLAN1'))
        self.assertTrue(self._test_case_is_network_in_white_list
                        (['VLAN1', 'V2'], 'V2'))
        self.assertFalse(self._test_case_is_network_in_white_list
                         (['VLAN1', 'V2'], 'V3'))
        self.assertTrue(self._test_case_is_network_in_white_list
                        (['VLAN1', 'V?'], 'V3'))
        self.assertTrue(self._test_case_is_network_in_white_list
                        (['VLAN1', 'V[34]'], 'V3'))
        self.assertFalse(self._test_case_is_network_in_white_list
                         (['VLAN1', 'V[34]'], 'V5'))

    def _test_case_is_network_in_white_list(self, whitelist, net_name):

        self.moxer.StubOutWithMock(utils, "_get_map_white_list")
        utils._get_map_white_list().AndReturn(whitelist)
        self.moxer.ReplayAll()
        net = {'name': net_name}
        rtn = utils.is_network_in_white_list(net)
        self.moxer.VerifyAll()
        self.moxer.UnsetStubs()
        return rtn
