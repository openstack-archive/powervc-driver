from setuptools import setup, find_packages

setup(
    name="hostmaintenance-client",
    version="0.1",
    packages=find_packages(exclude=['*.tests', 'tests',
                                    'tests.*', '*.tests.*']),
    entry_points={
        'novaclient.extension': [
            'host_maintenance = v1_1.host_maintenance',
        ],
    }
)
