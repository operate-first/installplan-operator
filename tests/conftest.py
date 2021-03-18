import pytest

import openshift.dynamic.exceptions as openshift_exc
from unittest import mock

import installplan_operator.main


class AttrDict(dict):
    '''A dictionary that permits attribute access.

    This is used to fake the return values from the OpenShift
    dynamic client API.'''

    def __init__(self, model):
        for k, v in model.items():
            if isinstance(v, dict):
                v = AttrDict(v)

            super().__setitem__(k, v)

    def __getattr__(self, k):
        return super().__getitem__(k)

    def __setattr__(self, k, v):
        super().__setitem__(k, v)


@pytest.fixture
def testdata():
    '''Common configuration and mock resources for the test_process_* tests'''

    return dict(
        updateconfig={
            'name': 'test-operator',
            'namespace': 'test-ns',
            'version': 'test-operator-1.0',
        },
        subscription=AttrDict({
            'status': {
                'installPlanRef': {
                    'name': 'test-operator',
                }
            }
        }),
        installplan=AttrDict({
            'spec': {
                'approved': False,
                'clusterServiceVersionNames': [
                    'test-operator-1.0',
                ]
            }
        }),
    )


@pytest.fixture
def approver():
    '''An Approver with a mocked OpenShift client'''

    with mock.patch('installplan_operator.main.create_openshift_client'):
        approver = installplan_operator.main.Approver()
        return approver


@pytest.fixture
def approver_fake_events(approver):
    '''An Approver with a mocked OpenShift client and fake event stream'''

    approver.events = mock.Mock()
    approver.events.return_value = [('fake',), ('fake',)]
    return approver


@pytest.fixture
def not_found_error():
    return openshift_exc.NotFoundError(
        AttrDict({
            'status': 404,
            'reason': 'fake reason',
            'body': '',
            'headers': '',
        }),
    )


@pytest.fixture
def unauthorized_error():
    return openshift_exc.UnauthorizedError(
        AttrDict({
            'status': 403,
            'reason': 'fake reason',
            'body': '',
            'headers': '',
        }),
    )


@pytest.fixture
def api_error():
    return openshift_exc.DynamicApiError(
        AttrDict({
            'status': 400,
            'reason': 'fake reason',
            'body': '',
            'headers': '',
        }),
    )
