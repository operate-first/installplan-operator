import colorlog as logging
import kubernetes
import queue
import threading
import time
import yaml

from functools import cached_property
from itertools import chain
from openshift.dynamic import DynamicClient
from pathlib import Path
from watchgod import watch

import kubernetes.config.config_exception as kube_exc
import openshift.dynamic.exceptions as openshift_exc

from installplan_operator import config

LOG = logging.getLogger(__name__)


def create_openshift_client():
    try:
        kubernetes.config.load_incluster_config()
    except kube_exc.ConfigException:
        kubernetes.config.load_kube_config()

    k8s = kubernetes.client.ApiClient()
    return DynamicClient(k8s)


class SubscriptionWatcher(threading.Thread):
    '''Watch for events on Subscription resources'''

    def __init__(self, q, api):
        self.q = q
        self.api = api
        super().__init__(daemon=True)

    def run(self):
        for event in self.api.subscriptions.watch():
            self.q.put(('subscription', event))


class FileWatcher(threading.Thread):
    '''Watch for filesystem events in config_dir'''

    def __init__(self, q):
        self.q = q
        super().__init__(daemon=True)

    def run(self):
        for event in watch(config.config_dir):
            self.q.put(('fs', event))


class Approver:
    def __init__(self):
        self.oc = create_openshift_client()
        self.q = queue.Queue()

    def start_watchers(self):
        self.tasks = [
            FileWatcher(self.q),
            SubscriptionWatcher(self.q, self),
        ]

        for task in self.tasks:
            task.start()

    @cached_property
    def subscriptions(self):
        '''This is an API endpoint for listing/getting/watching subscriptions'''

        return self.oc.resources.get(
            api_version='operators.coreos.com/v1alpha1',
            kind='Subscription'
        )

    @cached_property
    def installplans(self):
        '''This is an API endpoint for listing/getting/watching installplans'''

        return self.oc.resources.get(
            api_version='operators.coreos.com/v1alpha1',
            kind='InstallPlan'
        )

    def events(self):
        '''An iterator that yields events from the queue.

        This method will synthesize a timeout event if no events
        are received from the queue after max_interval seconds.
        '''

        while True:
            # Wait up to max_interval seconds for an event
            try:
                event = self.q.get(timeout=config.max_interval)
            except queue.Empty:
                event = ('timeout',)

            yield event

    def loop(self):
        self.start_watchers()

        t_last = 0
        for event in self.events():
            t_start = time.time()
            t_delta = t_start - t_last

            # Ignore triggers if we last checked less than min_interval
            # seconds ago.
            if t_delta < config.min_interval:
                LOG.debug('ignoring %s event (too soon), t_last=%s, t_start=%s, t_delta=%s',
                          event[0],
                          t_last,
                          t_start,
                          t_delta)
                continue

            LOG.info('subscription check triggered by %s event', event[0])
            sub_count = self.process_update_specs()

            t_end = time.time()
            t_last = t_start
            t_delta = t_end - t_start

            LOG.info('finished subscription check; %s subscriptions in %s seconds',
                     sub_count,
                     t_delta)

    def process_update_specs(self):
        '''Iterate through update specifications in config_dir'''

        count = 0

        for specfile in chain(
                config.config_dir.glob('*.yml'),
                config.config_dir.glob('*.yaml')):
            if specfile.is_file():
                count += 1
                try:
                    self.process_update_spec(specfile)
                except openshift_exc.NotFoundError as err:
                    LOG.error('unable to find requested resource: %s', err.summary())

        return count

    def process_update_spec(self, specfile: Path):
        '''Process a single update specification'''

        with specfile.open('r') as fd:
            spec = yaml.safe_load(fd)

        LOG.info('processing subscription %s in namespace %s',
                 spec['name'],
                 spec['namespace'])

        # look up named subscription
        sub = self.subscriptions.get(name=spec['name'], namespace=spec['namespace'])

        # get current installplan
        plan_name = sub.status.installPlanRef.name
        LOG.debug('%s: got installplan %s',
                  spec['name'],
                  plan_name)
        plan = self.installplans.get(name=plan_name, namespace=spec['namespace'])
        have = plan.spec.clusterServiceVersionNames[0]

        # check if installplan matches request version
        if have != spec['version']:
            LOG.warning('%s: invalid version: have=%s, want=%s',
                        spec['name'],
                        have,
                        spec['version'])
            return

        # check if installplan was previously approved
        if plan.spec.approved:
            LOG.info('%s: version %s is already approved',
                     spec['name'],
                     spec['version'])
            return

        # approve the plan
        LOG.warning('%s: approve version %s%s',
                    spec['name'],
                    spec['version'],
                    '' if config.approve_updates else ' (dry run)')

        if config.approve_updates:
            plan.spec.approved = True
            self.installplans.patch(
                body=plan,
                namespace=spec['namespace'])


def setup_logging():
    color_format = (
        '%(blue)s%(asctime)s%(reset)s %(name)s '
        '%(log_color)s%(levelname)s%(reset)s '
        '%(message_log_color)s%(message)s%(reset)s'
    )

    mono_format = (
        '%(asctime)s %(name)s '
        '%(levelname)s '
        '%(message)s'
    )
    logging.basicConfig(
        level=config.log_level,
        format=color_format if config.colorize_logs else mono_format,
        datefmt='%Y-%m-%dT%H:%M:%S%z',
        secondary_log_colors=dict(message=dict(WARNING='red', ERROR='red'))
    )


def main():
    setup_logging()

    try:
        app = Approver()
        app.loop()
    except openshift_exc.UnauthorizedError as err:
        LOG.error('authorization failed: %s',  err.summary())
    except openshift_exc.DynamicApiError as err:
        LOG.error('unexpected openshift api error: %s', err.summary())
    except FileNotFoundError as err:
        LOG.error('unable to open config directory: %s', err)
