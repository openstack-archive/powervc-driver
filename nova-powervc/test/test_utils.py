# Copyright 2013 IBM Corp.

import testtools
import powervc.utils as utils_to_test


class UtilsTest(testtools.TestCase):
    """
    Class UtilsTest is used to provide testcases for
    powervc/utils.py
    """
    
    # Test UT Test
    def setUp(self):
        super(UtilsTest, self).setUp()

    def test_get_pvc_id_from_list_type_1(self):
        pvc_id_expected = '40e2d7c9-b510-4e10-8986-057800117714'
        metadata = [
            {'key': 'powervm:defer_placement', 'value': 'true'},
            {'key': 'pvc_id', 'value': pvc_id_expected}
        ]

        pvc_id = utils_to_test.get_pvc_id_from_metadata(metadata)
        self.assertEqual(pvc_id_expected, pvc_id,
                         'pvc_id matches on list type 1')

    def test_get_pvc_id_from_list_type_2(self):
        pvc_id_expected = '40e2d7c9-b510-4e10-8986-057800117714'
        metadata = [{
            "powervm:health_status.health_value": "OK",
            "pvc_id": pvc_id_expected
        }]

        pvc_id = utils_to_test.get_pvc_id_from_metadata(metadata)
        self.assertEqual(pvc_id_expected, pvc_id,
                         'pvc_id matches on list type 2')

    def test_get_pvc_id_from_dict_type(self):
        pvc_id_expected = '40e2d7c9-b510-4e10-8986-057800117714'
        metadata = {
            "powervm:health_status.health_value": "OK",
            "pvc_id": pvc_id_expected,
            "powervm:defer_placement": "Fale",
            "powervm:max_cpus": "1"
        }

        pvc_id = utils_to_test.get_pvc_id_from_metadata(metadata)
        self.assertEqual(pvc_id_expected, pvc_id,
                         'pvc_id matches on dict')
