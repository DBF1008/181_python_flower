import json
import os
import time
from collections import OrderedDict

from celery.events import Event

from flower.events import EventsState
from tests.unit import AsyncHTTPTestCase
from tests.unit.utils import task_failed_events, task_succeeded_events


class TaskTest(AsyncHTTPTestCase):
    def test_unknown_task(self):
        r = self.get('/task/unknown')
        self.assertEqual(404, r.code)
        self.assertTrue('Unknown task' in str(r.body))


class TasksTest(AsyncHTTPTestCase):
    def setUp(self):
        self.app = super().get_app()
        super().setUp()

    def get_app(self, capp=None):
        return self.app

    def test_no_task(self):
        r = self.get('/tasks')
        self.assertEqual(200, r.code)
        self.assertTrue('UUID' in str(r.body))
        self.assertNotIn('<tr id=', str(r.body))

    def test_succeeded_task(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='123')
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self.app.events.state = state

        params = dict(draw=1, start=0, length=10)
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(1, table['recordsTotal'])
        self.assertEqual(1, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(1, len(tasks))
        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('123', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])

    def test_failed_task(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_failed_events(worker='worker1', name='task1',
                                     id='123')
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self.app.events.state = state

        params = dict(draw=1, start=0, length=10)
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(1, table['recordsTotal'])
        self.assertEqual(1, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(1, len(tasks))
        self.assertEqual('FAILURE', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('123', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])

    def test_sort_runtime(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='2', runtime=10.0)
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='4', runtime=10000000.0)
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='3', runtime=20.0)
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='1', runtime=2.0)
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self.app.events.state = state

        params = dict(draw=1, start=0, length=10)
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'runtime'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(4, table['recordsTotal'])
        self.assertEqual(4, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(4, len(tasks))

        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('1', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])
        self.assertEqual(2.0, tasks[0]['runtime'])

        self.assertEqual('SUCCESS', tasks[1]['state'])
        self.assertEqual('task1', tasks[1]['name'])
        self.assertEqual('2', tasks[1]['uuid'])
        self.assertEqual('worker1', tasks[1]['worker'])
        self.assertEqual(10.0, tasks[1]['runtime'])

        self.assertEqual('SUCCESS', tasks[3]['state'])
        self.assertEqual('task1', tasks[3]['name'])
        self.assertEqual('4', tasks[3]['uuid'])
        self.assertEqual('worker1', tasks[3]['worker'])
        self.assertEqual(10000000.0, tasks[3]['runtime'])

    def test_sort_incomparable(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='123')
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='456', runtime=None)
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self.app.events.state = state

        params = dict(draw=1, start=0, length=10)
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'runtime'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(2, table['recordsTotal'])
        self.assertEqual(2, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(2, len(tasks))

        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('456', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])
        self.assertIsNone(tasks[0]['runtime'])

        self.assertEqual('SUCCESS', tasks[1]['state'])
        self.assertEqual('task1', tasks[1]['name'])
        self.assertEqual('123', tasks[1]['uuid'])
        self.assertEqual('worker1', tasks[1]['worker'])

    def test_pagination(self):
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1',
                                        id='123')
        events += task_succeeded_events(worker='worker1', name='task2',
                                        id='456')
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self.app.events.state = state

        params = dict(draw=1, start=0, length=10)
        params['search[value]'] = ''
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'
        params['start'] = '0'
        params['length'] = '1'

        r = self.get('/tasks/datatable?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(2, table['recordsTotal'])
        self.assertEqual(2, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(1, len(tasks))

        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task1', tasks[0]['name'])
        self.assertEqual('123', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])

        params['start'] = '1'
        params['length'] = '1'

        r = self.get('/tasks/datatable?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(2, table['recordsTotal'])
        self.assertEqual(2, table['recordsFiltered'])
        tasks = table['data']
        self.assertEqual(1, len(tasks))

        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('task2', tasks[0]['name'])
        self.assertEqual('456', tasks[0]['uuid'])
        self.assertEqual('worker1', tasks[0]['worker'])

    def test_records_filtered_with_search(self):
        """recordsFiltered should differ from recordsTotal when search is active."""
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task_alpha', id='1')
        events += task_succeeded_events(worker='worker1', name='task_beta', id='2')
        events += task_succeeded_events(worker='worker1', name='other_job', id='3')
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self.app.events.state = state

        params = dict(draw=1, start=0, length=10)
        params['search[value]'] = 'task_'
        params['order[0][column]'] = 0
        params['columns[0][data]'] = 'name'
        params['order[0][dir]'] = 'asc'

        r = self.get('/tasks/datatable?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        self.assertEqual(3, table['recordsTotal'])
        self.assertEqual(2, table['recordsFiltered'])
        self.assertEqual(2, len(table['data']))

    def test_api_and_datatable_consistency(self):
        """Both endpoints should return the same tasks for equivalent queries."""
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task_a',
                                        id='aaa', runtime=3.0)
        events += task_succeeded_events(worker='worker1', name='task_b',
                                        id='bbb', runtime=1.0)
        events += task_succeeded_events(worker='worker1', name='task_c',
                                        id='ccc', runtime=2.0)
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self.app.events.state = state

        # Query via DataTable
        dt_params = dict(draw=1, start=0, length=10)
        dt_params['search[value]'] = ''
        dt_params['order[0][column]'] = 0
        dt_params['columns[0][data]'] = 'name'
        dt_params['order[0][dir]'] = 'asc'

        r_dt = self.get('/tasks/datatable?' + '&'.join(
            map(lambda x: '%s=%s' % x, dt_params.items())))
        dt_data = json.loads(r_dt.body.decode("utf-8"))

        # Query via API
        os.environ['FLOWER_UNAUTHENTICATED_API'] = 'true'
        try:
            api_params = dict(sort_by='name', limit=10, offset=0)
            r_api = self.get('/api/tasks?' + '&'.join(
                map(lambda x: '%s=%s' % x, api_params.items())))
            api_data = json.loads(r_api.body.decode("utf-8"),
                                  object_pairs_hook=OrderedDict)
        finally:
            del os.environ['FLOWER_UNAUTHENTICATED_API']

        # Compare task UUIDs and names in order
        dt_uuids = [t['uuid'] for t in dt_data['data']]
        api_uuids = list(api_data.keys())
        self.assertEqual(dt_uuids, api_uuids)

        dt_names = [t['name'] for t in dt_data['data']]
        api_names = [v['name'] for v in api_data.values()]
        self.assertEqual(dt_names, api_names)

    def test_sort_by_state_descending(self):
        """DataTable should correctly sort by state in descending order."""
        state = EventsState()
        state.get_or_create_worker('worker1')
        events = [Event('worker-online', hostname='worker1')]
        events += task_succeeded_events(worker='worker1', name='task1', id='1')
        events += task_failed_events(worker='worker1', name='task2', id='2')
        events += task_succeeded_events(worker='worker1', name='task3', id='3')
        for i, e in enumerate(events):
            e['clock'] = i
            e['local_received'] = time.time()
            state.event(e)
        self.app.events.state = state

        params = dict(draw=1, start=0, length=10)
        params['search[value]'] = ''
        params['order[0][column]'] = 2
        params['columns[2][data]'] = 'state'
        params['order[0][dir]'] = 'desc'

        r = self.get('/tasks/datatable?' + '&'.join(
            map(lambda x: '%s=%s' % x, params.items())))

        table = json.loads(r.body.decode("utf-8"))
        self.assertEqual(200, r.code)
        tasks = table['data']
        self.assertEqual(3, len(tasks))
        # SUCCESS sorts after FAILURE alphabetically
        self.assertEqual('SUCCESS', tasks[0]['state'])
        self.assertEqual('SUCCESS', tasks[1]['state'])
        self.assertEqual('FAILURE', tasks[2]['state'])
