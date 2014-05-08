import unittest
import mox

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
            # Disable DB init.
            db_api.get_session = dummy
            db_api.configure_db = dummy
            self._db = powervc_db_v2.PowerVCAgentDB()
            self._callback = PVCRpcCallbacks(self)
            # Replace with the dummy DB.
            self._callback.db = self._db
            self.moxer = mox.Mox()

        def get_db_api(self):
            return self._db

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

            self.moxer.StubOutWithMock(self._db, "get_network")
            self._db.get_network(local_id=id_in).AndReturn(id_out)

            self.moxer.ReplayAll()

            rtn = self._callback.get_pvc_network_uuid(context, id_in)

            self.moxer.VerifyAll()
            self.moxer.UnsetStubs()

            print str(rtn)
            return rtn
