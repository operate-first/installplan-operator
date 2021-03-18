from setuptools import setup, find_packages

setup(
    name='installplan-operator',
    version='0.1.0',
    url='https://github.com/operate-first/installplan-operator.git',
    author='Lars Kellogg-Stedman',
    author_email='lars@redhat.com',
    description='Use declarative configuration to approve pending operator updates in OpenShift',
    packages=find_packages(),
    install_requires=[
        'colorlog',
        'kubernetes',
        'openshift',
        'python-decouple',
        'pyyaml',
        'watchgod',
    ],
    entry_points={
        'console_scripts': [
            'installplan-operator=installplan_operator.main:main'
        ]
    }
)
