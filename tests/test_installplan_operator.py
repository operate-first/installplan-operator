import os
import queue
import time
import yaml

from pathlib import Path
from unittest import mock

import installplan_operator.main
import installplan_operator.config

installplan_operator.config.min_interval = 1
installplan_operator.config.max_interval = 2
installplan_operator.config.approve_updates = True


def test_event_timeout(approver, tmp_path):
    '''Test that the events method delivers timeout events'''

    with mock.patch('installplan_operator.config.config_dir', new=tmp_path):
        event = next(approver.events())
        assert event[0] == 'timeout'


def test_event_file(approver, tmp_path):
    '''Test that we respond to filesystem changes'''

    with mock.patch('installplan_operator.config.config_dir', new=tmp_path), \
            mock.patch('installplan_operator.config.max_interval', new=5):
        q = queue.Queue()
        watcher = installplan_operator.main.FileWatcher(q)
        watcher.start()

        # we need to make sure the watcher is running before we
        # create a file
        time.sleep(1)

        with open(os.path.join(tmp_path, 'testfile'), 'w') as fd:
            fd.write('this is a test\n')

        event = q.get(timeout=5)
        assert event[0] == 'fs'


def test_event_subscription(approver):
    '''Test that we respond to subscription events'''

    mock_resource = mock.Mock()
    mock_resource.watch.return_value = ['Fake event']
    approver.oc.resources.get.return_value = mock_resource

    q = queue.Queue()
    watcher = installplan_operator.main.SubscriptionWatcher(q, approver)
    watcher.start()

    # we need to make sure the watcher is running before we
    # test the result
    time.sleep(1)

    event = q.get(timeout=5)
    assert event[0] == 'subscription'


def test_subscriptions(approver):
    '''Test that we call the expected API for Subscriptions'''

    approver.subscriptions
    assert approver.oc.resources.get.call_args_list[0][1] == {
        'api_version': 'operators.coreos.com/v1alpha1',
        'kind': 'Subscription',
    }


def test_installplans(approver):
    '''Test that we call the expected API for InstallPlans'''

    approver.installplans
    assert approver.oc.resources.get.call_args_list[0][1] == {
        'api_version': 'operators.coreos.com/v1alpha1',
        'kind': 'InstallPlan',
    }


def test_file_glob(approver, tmp_path):
    '''Test that our file discovery works as expected'''

    good_paths = [
        Path(tmp_path) / 'testfile.yml',
        Path(tmp_path) / 'testfile.yaml'
    ]

    bad_paths = [
        Path(tmp_path) / 'testfile.gz',
    ]

    for p in good_paths + bad_paths:
        p.open('w').close()

    with mock.patch('installplan_operator.config.config_dir', new=tmp_path):
        mock_process = mock.Mock()
        approver.process_update_spec = mock_process
        count = approver.process_update_specs()
        args = [x[0][0] for x in mock_process.call_args_list]

        assert count == 2
        for p in good_paths:
            assert p in args
        for p in bad_paths:
            assert p not in args


def test_process_spec_approve(approver_fake_events, tmp_path, testdata):
    '''Test that we approve an InstallPlan that matches our criteria'''

    mock_resource = mock.Mock()
    mock_resource.watch.return_value = []
    mock_resource.get.side_effect = [
        testdata['subscription'],
        testdata['installplan'],
    ]
    approver_fake_events.oc.resources.get.return_value = mock_resource

    with open(os.path.join(tmp_path, 'updateconfig.yaml'), 'w') as fd:
        yaml.safe_dump(testdata['updateconfig'], stream=fd)

    with mock.patch('installplan_operator.config.config_dir', new=tmp_path):
        approver_fake_events.loop()

    assert mock_resource.patch.call_args_list[0][1] == {
        'body': {
            'spec': {
                'approved': True,
                'clusterServiceVersionNames': [
                    'test-operator-1.0'
                ]
            }
        },
        'namespace': 'test-ns'
    }


def test_process_spec_already_approved(approver_fake_events, tmp_path, testdata, caplog):
    '''Test that we don't attempt to approve an already approved InstallPlan'''

    testdata['installplan'].spec.approved = True

    mock_resource = mock.Mock()
    mock_resource.watch.return_value = []
    mock_resource.get.side_effect = [
        testdata['subscription'],
        testdata['installplan'],
    ]
    approver_fake_events.oc.resources.get.return_value = mock_resource

    with open(os.path.join(tmp_path, 'updateconfig.yaml'), 'w') as fd:
        yaml.safe_dump(testdata['updateconfig'], stream=fd)

    with caplog.at_level('INFO'):
        with mock.patch('installplan_operator.config.config_dir', new=tmp_path):
            approver_fake_events.loop()

    assert not mock_resource.patch.called
    assert 'is already approved' in caplog.text


def test_process_spec_wrong_version(approver_fake_events, tmp_path, testdata, caplog):
    '''Test that we don't approve an InstallPlan with an incorrect version'''

    testdata['installplan'].spec.clusterServiceVersionNames = [
        'test-operator-2.0',
    ]

    mock_resource = mock.Mock()
    mock_resource.watch.return_value = []
    mock_resource.get.side_effect = [
        testdata['subscription'],
        testdata['installplan'],
    ]
    approver_fake_events.oc.resources.get.return_value = mock_resource

    with open(os.path.join(tmp_path, 'updateconfig.yaml'), 'w') as fd:
        yaml.safe_dump(testdata['updateconfig'], stream=fd)

    with mock.patch('installplan_operator.config.config_dir', new=tmp_path):
        approver_fake_events.loop()

    assert not mock_resource.patch.called
    assert 'invalid version' in caplog.text


def test_process_spec_missing_subscription(approver_fake_events, testdata,
                                           tmp_path, caplog, not_found_error):
    '''Test that we handle a missing subscription correctly'''

    mock_resource = mock.Mock()
    mock_resource.watch.return_value = []
    mock_resource.get.side_effect = not_found_error
    approver_fake_events.oc.resources.get.return_value = mock_resource

    with open(os.path.join(tmp_path, 'updateconfig.yaml'), 'w') as fd:
        yaml.safe_dump(testdata['updateconfig'], stream=fd)

    with mock.patch('installplan_operator.config.config_dir', new=tmp_path):
        approver_fake_events.loop()

    assert not mock_resource.patch.called
    assert 'unable to find requested resource' in caplog.text


def test_main():
    '''Test that the main method executes correctly when there are no errors'''

    with mock.patch('installplan_operator.main.Approver') as mock_approver_class:
        mock_approver = mock.Mock()
        mock_approver_class.return_value = mock_approver
        installplan_operator.main.main()


def test_main_unauthorized(caplog, unauthorized_error):
    '''Test that we respond correctly to an Unauthorized condition'''

    with mock.patch('installplan_operator.main.Approver') as mock_approver_class:
        mock_approver = mock.Mock()
        mock_approver_class.return_value = mock_approver
        mock_approver.loop.side_effect = unauthorized_error
        installplan_operator.main.main()
        assert 'authorization failed' in caplog.text


def test_main_api_error(caplog, api_error):
    '''Test that we respond correctly to general OpenShift API errors'''

    with mock.patch('installplan_operator.main.Approver') as mock_approver_class:
        mock_approver = mock.Mock()
        mock_approver_class.return_value = mock_approver
        mock_approver.loop.side_effect = api_error
        installplan_operator.main.main()
        assert 'unexpected openshift api error' in caplog.text


def test_main_file_not_found(caplog):
    '''Test that we respond correctly to FileNotFound errors'''

    with mock.patch('installplan_operator.main.Approver') as mock_approver_class:
        mock_approver = mock.Mock()
        mock_approver_class.return_value = mock_approver
        mock_approver.loop.side_effect = FileNotFoundError('testfile')
        installplan_operator.main.main()
        assert 'unable to open config directory' in caplog.text
