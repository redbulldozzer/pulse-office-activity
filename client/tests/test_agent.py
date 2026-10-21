import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from office_activity.core import Accounting, Identity, Snapshot, Store
from office_activity.identity import Resolver, shared_identity
from office_activity.transport import upload


def person(name='employee1', shift='a'*32):
    return Identity('domain_shared', name, 'example.invalid', 'office-workspace', 1001, shift, 'c2')


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.engine = Accounting('device', 'boot', self.events.append, flush_seconds=5)
        self.a = Snapshot(person(), 'active')

    def tick(self, t, snapshot=None, key=False, wall_offset=0):
        self.engine.observe(snapshot or self.a, 1700000000+t+wall_offset, t, key)

    def test_equal_counts_not_merged_or_lost(self):
        self.tick(0)
        for t in range(1, 11):
            self.tick(t, key=True)
        self.engine.flush()
        self.assertEqual(sum(e['key_presses'] for e in self.events), 10)
        self.assertEqual(len(self.events), 2)
        self.assertNotEqual(self.events[0]['event_id'], self.events[1]['event_id'])

    def test_takeover_discards_boundary_key_but_never_mixes(self):
        b = Snapshot(person('employee2', 'b'*32), 'active')
        self.tick(0)
        self.tick(1, key=True)
        self.tick(2, b, key=True)
        self.tick(3, b, key=True)
        self.engine.flush()
        counts = {}
        for e in self.events:
            if e['identity']:
                name = e['identity']['principal']
                counts[name] = counts.get(name, 0)+e['key_presses']
        self.assertEqual(counts, {'employee1': 1, 'employee2': 1})
        self.assertEqual(sum(e['boundary_key_drops'] for e in self.events), 1)
        self.assertTrue(any(e['reason'] == 'state_transition' for e in self.events))

    def test_locked_input_never_counted(self):
        self.tick(0)
        locked = Snapshot(person(), 'locked')
        for t in range(1, 8):
            self.tick(t, locked, key=True)
        self.engine.flush()
        self.assertEqual(sum(e['key_presses'] for e in self.events), 0)

    def test_missing_identity_never_attributed(self):
        self.tick(0, Snapshot(None, 'unknown'))
        self.tick(1, Snapshot(None, 'unknown'), key=True)
        self.engine.flush()
        self.assertTrue(all(e['identity'] is None and e['key_presses'] == 0 for e in self.events))

    def test_resume_gap_is_unknown(self):
        self.tick(0)
        self.tick(1, key=True)
        self.tick(3601)
        self.engine.flush()
        gap = next(e for e in self.events if e['reason'] == 'observation_gap')
        self.assertEqual(gap['duration_ms'], 3600000)
        self.assertIsNone(gap['identity'])
        self.assertEqual(gap['key_presses'], 0)

    def test_clock_change_never_inflates_active_time(self):
        self.tick(0)
        self.tick(1, key=True)
        self.tick(2, wall_offset=86400)
        self.tick(3, wall_offset=86400)
        self.engine.flush()
        self.assertLess(sum(e['duration_ms'] for e in self.events), 10000)
        self.assertTrue(any(e['reason'] == 'clock_changed' for e in self.events))

    def test_first_key_after_afk_is_counted(self):
        self.tick(0, Snapshot(person(), 'afk'))
        self.tick(1, key=True)
        self.engine.flush()
        self.assertEqual(sum(e['key_presses'] for e in self.events), 1)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        (self.path/'current').write_text('employee=employee1\nshift='+'a'*32+'\npid=999999\n')
        self.lock = (self.path/'session.lock').open('w')
        (self.path/'session.lock').chmod(0o644)
        (self.path/'current').chmod(0o644)
    def tearDown(self):
        self.lock.close()
        self.temp.cleanup()

    def test_stale_file_without_lock_rejected(self):
        with self.assertRaises(ValueError):
            shared_identity(self.path, os.getuid())

    def test_live_lock_is_authoritative_not_pid(self):
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.assertEqual(shared_identity(self.path, os.getuid()), ('employee1', 'a'*32))

    def test_symlink_rejected(self):
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        (self.path/'current').rename(self.path/'other')
        (self.path/'current').symlink_to(self.path/'other')
        with self.assertRaises(OSError):
            shared_identity(self.path, os.getuid())

    def test_writable_identity_rejected(self):
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        (self.path/'current').chmod(0o666)
        with self.assertRaises(ValueError):
            shared_identity(self.path, os.getuid())

    def test_local_session_never_inherits_domain_employee(self):
        r = Resolver.__new__(Resolver)
        r.uid, r.user, r.session, r.target, r.realm, r.local = 1000, 'example-user', 'c1', 'office-workspace', 'example.invalid', {'example-user'}
        props = {'User': (1000, '/u'), 'Class': 'user', 'Remote': False, 'Type': 'x11', 'State': 'active', 'Active': True}
        with patch('office_activity.identity.shared_identity', side_effect=AssertionError('must not be read')):
            s = r.resolve(props)
        self.assertEqual(s.identity.account_type, 'local')
        self.assertEqual(s.identity.principal, 'example-user')
        props['User'] = (1001, '/u')
        self.assertIsNone(r.resolve(props).identity)

    def test_domain_uid_is_frozen_for_authenticated_shift(self):
        r = Resolver.__new__(Resolver)
        r.uid, r.user, r.session, r.target, r.realm, r.local = 1001, 'office-workspace', 'c2', 'office-workspace', 'example.invalid', {'office-workspace'}
        r.domain_ids = {}
        props = {'User': (1001, '/u'), 'Class': 'user', 'Remote': False, 'Type': 'x11', 'State': 'active', 'Active': True}
        with patch('office_activity.identity.shared_identity', return_value=('employee1', 'a'*32)), \
             patch('office_activity.identity.pwd.getpwnam') as lookup:
            lookup.return_value.pw_uid = 373400010
            self.assertEqual(r.resolve(props).identity.domain_uid, 373400010)
            lookup.return_value.pw_uid = 373400999
            self.assertEqual(r.resolve(props).identity.domain_uid, 373400010)
            lookup.assert_called_once()


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'events.db'
        self.store = Store(self.path)
        self.event = {'event_id': str(uuid.uuid4()), 'identity': {'principal': 'employee1'}, 'key_presses': 12}
    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_restart_preserves_pending_and_identity(self):
        self.store.put(self.event)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.pending(), [self.event])

    def test_retries_do_not_duplicate_queue(self):
        self.store.put(self.event)
        self.store.put(self.event)
        self.assertEqual(len(self.store.pending()), 1)
        self.store.acknowledge([self.event['event_id']])
        self.assertEqual(self.store.pending(), [])

    def test_local_only_does_not_require_network_or_token(self):
        self.store.put(self.event)
        self.assertEqual(upload(self.store, {'endpoint': ''}, '/missing'), 'local_only')
        self.assertEqual(len(self.store.pending()), 1)

    def test_http_is_rejected(self):
        with self.assertRaises(ValueError):
            upload(self.store, {'endpoint': 'http://example.test/events'}, '/missing')

    def test_invalid_ack_keeps_pending(self):
        self.store.put(self.event)
        token = Path(self.temp.name)/'token'
        token.write_text('test-token'); token.chmod(0o600)
        with patch('urllib.request.build_opener') as builder:
            builder.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"accepted_event_ids":["wrong-id"]}'
            with self.assertRaises(ValueError):
                upload(self.store, {'endpoint': 'https://example.test/events', 'device_id': 'device'}, token)
        self.assertEqual(len(self.store.pending()), 1)

    def test_partial_ack_only_marks_accepted_events(self):
        other = {**self.event, 'event_id': str(uuid.uuid4())}
        self.store.put(self.event); self.store.put(other)
        token = Path(self.temp.name)/'token'
        token.write_text('test-token'); token.chmod(0o600)
        with patch('urllib.request.build_opener') as builder:
            builder.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps({'accepted_event_ids': [self.event['event_id']]}).encode()
            upload(self.store, {'endpoint': 'https://example.test/events', 'device_id': 'device'}, token)
        self.assertEqual(self.store.pending(), [other])


if __name__ == '__main__':
    unittest.main()
