import unittest
import mock

import neutron.db.api as db_api
from powervc.neutron.api.powervc_rpc import PVCRpcCallbacks
from powervc.neutron.db import powervc_db_v2


class FakeCTX():

    user_id = None
    project_id = None

    def __init__(self):

        self.user_id = "testuser"
        self.project_id = "testproject"

    def update(self, **update):

        if not update:
            self.user_id = update['user_id']
            self.project_id = update['project_id']


def dummy():
    pass


class TestSyncInstance(unittest.TestCase):

        def setUp(self):
            powervc_db_v2.PowerVCAgentDB = mock.MagicMock()
            self._callback = PVCRpcCallbacks(self)
            self._callback.db = mock.MagicMock()

        def tearDown(self):
            pass

        def test_get_pvc_network_uuid(self):
            rtn = self._get_pvc_network_uuid(None, None)
            self.assertEqual(None, rtn, "Should be None.")

            rtn = self._get_pvc_network_uuid("", None)
            self.assertEqual(None, rtn, "Should be None")

            rtn = self._get_pvc_network_uuid("123", {'pvc_id': 'pvc123'})
            self.assertEqual("pvc123", rtn)

        def _get_pvc_network_uuid(self, id_in, id_out):

            context = FakeCTX()

            self._callback.db.get_network = mock.MagicMock(return_value=id_out)
            rtn = self._callback.get_pvc_network_uuid(context, id_in)

            print str(rtn)
            return rtn
