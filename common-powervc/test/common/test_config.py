# Copyright 2013 IBM Corp.


import mock
import testtools
import os

from powervc.common import config


class PVCConfigTest(testtools.TestCase):

    def setUp(self):
        super(PVCConfigTest, self).setUp()

    def tearDown(self):
        super(PVCConfigTest, self).tearDown()
        del config.parse_power_config.power_config_loaded

    def test_parse_config_1(self):
        p1 = mock.patch(
            'oslo.config.cfg.find_config_files',
            new=mock.MagicMock(
                return_value=["%s%s%s" % (os.path.dirname(__file__),
                                          os.sep,
                                          "powervc_test_1.conf")]
            )
        )
        try:
            p1.start()
            config.parse_power_config([], "powervc-baseproject", None)
            # default value
            self.assertEqual(config.CONF.powervc.auth_url,
                             "http://localhost:5000/v2.0/")
            # value in file
            self.assertEqual(config.CONF.powervc.qpid_port, 5679)
        finally:
            p1.stop()

    def test_parse_config_2(self):
        p2 = mock.patch(
            'oslo.config.cfg.find_config_files',
            new=mock.MagicMock(
                side_effect=[["%s%s%s" % (os.path.dirname(__file__),
                                          os.sep,
                                          "powervc_test_1.conf")],
                             ["%s%s%s" % (os.path.dirname(__file__),
                                          os.sep,
                                          "powervc_test_2.conf")]]
            )
        )
        try:
            p2.start()
            config.parse_power_config([], "baseproject", None)
            # extend value in second file
            self.assertEqual(config.CONF.powervc.qpid_username,
                             "powervc_qpid_2")
        finally:
            p2.stop()
