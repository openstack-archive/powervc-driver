COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""
import unittest
from powervc.common.messaging import QpidConnection


class QpidTest(unittest.TestCase):

    def setUp(self):
        super(QpidTest, self).setUp()
        self.conn = QpidConnection(url='127.0.0.1:5989',
                                   username='test_username',
                                   password='test_passwd',
                                   transport='tcp',
                                   reconnection_interval=60,
                                   reconnect_handler=None,
                                   context=None,
                                   log=None)

    def test_create_listener(self):
        self.listener = self.conn.\
            create_listener('test_exchange', 'test_topic')
        self.assertNotEqual(self.listener, None)
        self.assertEqual([self.listener], self.conn._listeners)

    def test_register_handler(self):
        def _fake_handler():
            pass

        if not hasattr(self, 'listener'):
            self.listener = self.conn.\
                create_listener('test_exchange', 'test_topic')

        self.listener.register_handler('foo.bar.*', _fake_handler)
        self.assertEqual(self.listener._handler_map['foo.bar.*'],
                         _fake_handler)

    def test_unregister_handler(self):
        def _fake_handler():
            pass

        if not hasattr(self, 'listener'):
            self.listener = self.conn.\
                create_listener('test_exchange', 'test_topic')

        self.listener.register_handler('foo.bar.*', _fake_handler)
        self.assertEqual(self.listener._handler_map['foo.bar.*'],
                         _fake_handler)
        self.listener.unregister_handler('foo.bar.*')
        self.assertEqual(self.listener._handler_map,
                         {})

    def tearDown(self):
        unittest.TestCase.tearDown(self)

if __name__ == "__main__":
    unittest.main()
