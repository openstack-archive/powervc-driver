COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""


import testtools

from powervc.common import netutils


class PVCNetUtilsTest(testtools.TestCase):

    def setUp(self):
        super(PVCNetUtilsTest, self).setUp()

    def tearDown(self):
        super(PVCNetUtilsTest, self).tearDown()

    def test_is_ipv4_address_1(self):
        isipv4_address = netutils.is_ipv4_address("localhost")
        self.assertFalse(isipv4_address)

    def test_is_ipv4_address_2(self):
        isipv4_address = netutils.is_ipv4_address("127.0.0.1")
        self.assertTrue(isipv4_address)

    def test_hostname_url_1(self):
        url = netutils.hostname_url("http://127.0.0.1:5000/v2.0")
        self.assertEqual(url, "http://127.0.0.1:5000/v2.0")

    def test_hostname_url_2(self):
        url = netutils\
            .hostname_url("https://9.110.75.155/powervc/openstack/identity/v3")
        self.assertEqual(url,
                         "https://9.110.75.155/powervc/openstack/identity/v3")

    def test_hostname_url_3(self):
        url = netutils.hostname_url("http://random_host:5000/v2.0")
        self.assertEqual(url, "http://random_host:5000/v2.0")
