COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

import unittest
from powervc.common.client import delegate


class FakeDelegator1(object):
    def x(self):
        return 'x'


class FakeDelegator2(object):
    def y(self):
        return 'y'


class FakeContext(object):
    def __init__(self):
        self.auth_token = 'Context Auth Token'
        self.project_id = 'Project Id'


class FakeKeyStone(object):
    def __init__(self):
        self.auth_token = 'KeyStone Auth Token'


class DelegateTest(unittest.TestCase):

    def test_new_composite_deletgate(self):
        d1 = FakeDelegator1()
        d2 = FakeDelegator2()
        dele = delegate.new_composite_deletgate([d1, d2])
        self.assertEqual(dele.x(), 'x')
        self.assertEqual(dele.y(), 'y')

    def test_context_dynamic_auth_token(self):
        ctx = FakeContext()
        keystone = FakeKeyStone()
        dele_ctx_keystone = delegate.context_dynamic_auth_token(ctx, keystone)
        self.assertEqual(dele_ctx_keystone.auth_token, 'KeyStone Auth Token')
        self.assertEqual(dele_ctx_keystone.project_id, 'Project Id')

if __name__ == "__main__":
    unittest.main()
