powervc-driver Style Commandments
=======================

- Step 1: Read the OpenStack Style Commandments
  http://docs.openstack.org/developer/hacking/
- Step 2: Read on

Creating Unit Tests
-------------------
For every new feature, unit tests should be created that both test and
(implicitly) document the usage of said feature. If submitting a patch for a
bug that had no unit test, a new passing unit test should be added. If a
submitted bug fix does have a unit test, be sure to add a new one that fails
without the patch and passes with the patch.

For more information on creating unit tests and utilizing the testing
infrastructure in PowerVC Driver, please read ``TESTS_README.rst``.


Running Tests
-------------
In order to run the tests , you can simply run the script "run_tests.sh" . 
By default , it will run all the test cases for each component in the 
powervc-driver project.The script "run_tests.sh" offers various options to run 
the test suites , for more information , you can run the command 
"./run_tests.sh -h" to get the details.