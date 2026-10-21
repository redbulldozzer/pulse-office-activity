"""Real localhost TLS test, including loss of the first delivery acknowledgement."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest
import urllib.error

from office_activity.core import Store
from office_activity.transport import upload


class HttpsDeliveryTest(unittest.TestCase):
    def test_tls_retry_after_server_commit_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', str(p/'key.pem'), '-out', str(p/'cert.pem'), '-days', '1',
                '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1'],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            received = {}
            fail = [True]

            class Receiver(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass
                def do_POST(self):
                    if self.headers.get('Authorization') != 'Bearer test-token':
                        self.send_error(403)
                        return
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    for event in body['events']:
                        received[event['event_id']] = event
                    if fail.pop() if fail else False:
                        self.send_error(503)
                        return
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({'accepted_event_ids': [e['event_id'] for e in body['events']]}).encode())

            server = HTTPServer(('127.0.0.1', 0), Receiver)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(p/'cert.pem', p/'key.pem')
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            store = Store(p/'queue.db')
            token = p/'token';token.write_text('test-token');token.chmod(0o600)
            config = {'device_id': 'test-device', 'endpoint': f'https://127.0.0.1:{server.server_port}/v1/events',
                      'ca_file': str(p/'cert.pem')}
            event = {'event_id': 'stable-id', 'key_presses': 20,
                     'identity': {'principal': 'employee1', 'shift_id': 'before-offline'}}
            try:
                store.put(event)
                with self.assertRaises(urllib.error.HTTPError):
                    upload(store, config, token)
                self.assertEqual(len(store.pending()), 1)
                self.assertEqual(upload(store, config, token), 'uploaded')
                self.assertEqual(store.pending(), [])
                self.assertEqual(list(received.values()), [event])
                # A correct HTTPS URL with an untrusted certificate must still fail.
                store.put({**event, 'event_id': 'untrusted'})
                with self.assertRaises(urllib.error.URLError):
                    upload(store, {**config, 'ca_file': ''}, token)
                self.assertEqual(len(store.pending()), 1)
            finally:
                store.close()
                server.shutdown();server.server_close();thread.join(2)
