=====================================
PowerVC Driver Testing Infrastructure
=====================================

This README file attempts to provide current and prospective contributors with
everything they need to know in order to start creating unit tests for powervc-driver.


Test Types: Unit vs. Functional vs. Integration
-----------------------------------------------

TBD

Writing Unit Tests
------------------

Unit Test is required when one new feature is implemented in some component in the
powervc-driver.All the unit test files are located in the "$component_name/test"
folder.If you want to write a new unit test case , you should create a python
file in the test folder which name should start with "test" and append the new
feature for easy understanding.

Example :
    If the feature is to create an new vm , the unit test case file shoule be named "test_createvm.py"

The file content format example as bellow :

Example :
    import unittest


    class TestCreateVM(unittest.TestCase):
        """
        This method "setUp" is used to initialize the fake environment
	"""
	def setUp(self):

        """
	This method "tearDown" is used to cleanup the environment
	"""
	def tearDown(self):

	"""
	This method must be started with "test" and you can implement your unit test process in it
	"""
	def test_create_vm(self):


unittest.TestCase
-------------
The unittest module provides a rich set of tools for constructing and running tests. The
test case and test fixture concepts are supported through the TestCase class. When building
test fixtures using TestCase , the setUp() and tearDown() methods can be overridden to
provide initialization and cleanup for the fixture. The tests should be defined with methods
whose names start with the letters test. This naming convention informs the test runner about
which methods represent tests.

The crux of each test is a call to assertEqual() to check for an expected result; assertTrue()
to verify a condition; or assertRaises() to verify that an expected exception gets raised.
These methods are used instead of the assert statement so the test runner can accumulate all
test results and produce a report.
