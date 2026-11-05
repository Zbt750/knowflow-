"""Opt-in fresh Docker PostgreSQL for the existing isolated UI supervisor.

Never resumes/removes resources. Credentials remain process-local. Host binding
is loopback only; identities are checked before migration, seeding and stopping.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from uuid import uuid4

IMAGE = 'postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'
DOCKER = str(Path.home() / 'AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe')


class DockerTestPostgres:
    def __init__(self, *, station, port, audit):
        import re
        if not re.fullmatch(r'home[a-z0-9]{1,16}', station) or not 18000 <= port <= 65535 or port in {5433, 8000, 5173}:
            raise ValueError('invalid_docker_test_identity')
        self.port, self.audit = port, audit
        self.name = 'naiwa-ui-' + station
        self.volume = self.name + '-data'
        # The application URL must satisfy tests/conftest.py's explicit
        # *_test guard. The bootstrap `postgres` database is only for admin
        # operations and must never be exposed as TEST_DATABASE_URL.
        self.test_database = 'kaoyan_' + station + '_test'
        self.run_id = str(uuid4())
        self._passwords = {'kaoyan_admin': secrets.token_hex(24), 'kaoyan_app': secrets.token_hex(24)}
        self._owned_identity = None

    def _cmd(self, *args, env=None):
        result = subprocess.run([DOCKER, *args], env=env, capture_output=True, text=True, timeout=40,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            # Docker command lines and errors can contain connection details.
            raise RuntimeError('docker_test_command_failed:' + args[0] + ':' + str(result.returncode))
        return result.stdout

    def start(self):
        if self._cmd('container', 'ls', '-a', '--filter', 'name=^/' + self.name + '$', '-q').strip():
            raise RuntimeError('docker_test_container_already_exists')
        if self.volume in self._cmd('volume', 'ls', '--format', '{{.Name}}').splitlines():
            raise RuntimeError('docker_test_volume_already_exists')
        image = json.loads(self._cmd('image', 'inspect', IMAGE))[0]
        if image.get('Architecture') != 'amd64' or image.get('Os') != 'linux':
            raise RuntimeError('docker_test_image_platform_mismatch')
        self._cmd('volume', 'create', '--label', 'naiwa.run=' + self.run_id, self.volume)
        env = dict(os.environ, POSTGRES_PASSWORD=self._passwords['kaoyan_admin'])
        cid = self._cmd('run', '-d', '--name', self.name, '--label', 'naiwa.run=' + self.run_id,
                       '-p', f'127.0.0.1:{self.port}:{self.port}', '--mount',
                       f'type=volume,source={self.volume},target=/var/lib/postgresql/data',
                       '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_USER=kaoyan_admin',
                       '-e', 'POSTGRES_DB=postgres', IMAGE, 'postgres', '-p', str(self.port), env=env).strip()
        self._owned_identity = cid
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            try:
                self.identity('postgres', app=False)
                with self._connect() as db:
                    from psycopg import sql
                    db.execute(sql.SQL('CREATE ROLE kaoyan_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}').format(sql.Literal(self._passwords['kaoyan_app'])))
                    db.execute(sql.SQL("CREATE DATABASE {} OWNER kaoyan_app TEMPLATE template0 ENCODING 'UTF8'").format(
                        sql.Identifier(self.test_database)))
                self.identity(self.test_database)
                return
            except __import__('psycopg').OperationalError:
                time.sleep(.5)
        self.save_logs()
        raise RuntimeError('docker_test_start_timeout_no_retry_resources_retained')

    def _connect(self, user='kaoyan_admin', database='postgres'):
        import psycopg
        return psycopg.connect(host='127.0.0.1', port=self.port, user=user,
                               password=self._passwords[user], dbname=database, autocommit=True, connect_timeout=2)

    @property
    def database_url(self):
        from sqlalchemy.engine import URL
        return URL.create('postgresql+psycopg', username='kaoyan_app', password=self._passwords['kaoyan_app'],
                          host='127.0.0.1', port=self.port, database=self.test_database).render_as_string(hide_password=False)

    def _assert_owned_resources(self):
        if not self._owned_identity:
            raise RuntimeError('docker_test_container_identity_unavailable')
        info = json.loads(self._cmd('inspect', self.name))[0]
        vol = json.loads(self._cmd('volume', 'inspect', self.volume))[0]
        if info['Id'] != self._owned_identity or info['Config']['Labels'].get('naiwa.run') != self.run_id or vol['Labels'].get('naiwa.run') != self.run_id:
            raise RuntimeError('docker_test_resource_identity_changed')
        binds = info['HostConfig']['PortBindings']
        if binds != {f'{self.port}/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(self.port)}]}:
            raise RuntimeError('docker_test_port_binding_changed')
        mounts = [x for x in info['Mounts'] if x['Destination'] == '/var/lib/postgresql/data']
        if len(mounts) != 1 or mounts[0]['Name'] != self.volume:
            raise RuntimeError('docker_test_volume_changed')
        return info, vol

    def identity(self, database, app=True):
        self._assert_owned_resources()
        with self._connect(user='kaoyan_app' if app else 'kaoyan_admin', database=database) as db:
            row = db.execute('SELECT current_database(), current_user, inet_server_port()').fetchone()
        with self._connect() as db:
            sid = str(db.execute('SELECT system_identifier FROM pg_control_system()').fetchone()[0])
            directory = db.execute('SHOW data_directory').fetchone()[0]
        if row != (database, 'kaoyan_app' if app else 'kaoyan_admin', self.port) or (app and not database.endswith('_test')) or directory != '/var/lib/postgresql/data':
            raise RuntimeError('docker_test_database_identity_mismatch')
        if app:
            with self._connect(user='kaoyan_admin', database='postgres') as db:
                owner = db.execute('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s', (database,)).fetchone()
            if owner is None or owner[0] != 'kaoyan_app':
                raise RuntimeError('docker_test_database_owner_mismatch')
        if hasattr(self, 'system_id') and sid != self.system_id:
            raise RuntimeError('docker_test_system_identifier_changed')
        self.system_id = sid
        return dict(database=database, role=row[1], host='127.0.0.1', port=self.port,
                    container_id=self._owned_identity, volume=self.volume, cluster_id=self.run_id,
                    data_directory=directory, postgres_system_identifier=sid,
                    data_directory_proof='exact new labelled container, volume, port and server system identifier',
                    cluster_created_for_this_acceptance=True, image=IMAGE)

    def save_logs(self):
        self.audit.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([DOCKER, 'logs', self.name], capture_output=True, text=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        content = result.stdout + result.stderr
        for secret in self._passwords.values():
            content = content.replace(secret, '[REDACTED]')
        (self.audit / (self.name + '-postgres.log')).write_text(content, encoding='utf-8')

    def stop(self):
        # Stopping an owned container after a readiness timeout must not
        # depend on PostgreSQL accepting connections. Resource labels, exact
        # container ID, loopback port binding and volume identity are enough
        # to establish ownership; if any differ, refuse to stop it.
        self._assert_owned_resources()
        self.save_logs()
        self._cmd('stop', '--time', '15', self.name)
