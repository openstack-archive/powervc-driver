import unittest
import mock
from mock import patch


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


class TestSyncInstance(unittest.TestCase):

        def setUp(self):
            self._dbapi_session = patch('neutron.db.api.get_session')
            self._dbapi_engine = patch('neutron.db.api.get_engine')
            self._dbapi_session.start()
            self._dbapi_engine.start()
            from powervc.neutron.db import powervc_db_v2
            self._db = powervc_db_v2.PowerVCAgentDB()

            from powervc.neutron.api.powervc_rpc import PVCRpcCallbacks
            self._callback = PVCRpcCallbacks(self)
            # Replace with the dummy DB.
            self._callback.db = self._db

        def get_db_api(self):
            return self._db

        def tearDown(self):
            self._dbapi_session.stop()
            self._dbapi_engine.stop()

        def test_get_pvc_network_uuid(self):
            rtn = self._get_pvc_network_uuid(None, None)
            self.assertEqual(None, rtn, "Should be None.")

            rtn = self._get_pvc_network_uuid("", None)
            self.assertEqual(None, rtn, "Should be None")

            rtn = self._get_pvc_network_uuid("123", {'pvc_id': 'pvc123'})
            self.assertEqual("pvc123", rtn)

        def _get_pvc_network_uuid(self, id_in, id_out):

            context = FakeCTX()

            self._db.get_network =\
                mock.MagicMock(side_effect=[id_out])

            rtn = self._callback.get_pvc_network_uuid(context, id_in)

            print str(rtn)
            return rtn
