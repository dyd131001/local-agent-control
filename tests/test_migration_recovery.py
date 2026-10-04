"""SQLite migration recovery keeps data and rolls DDL back as one unit."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app import db as database


class MigrationRecoveryTest(unittest.TestCase):
    def test_partial_0010_recovers_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'control.db'
            engine = create_engine(f'sqlite:///{path}')
            cfg = Config()
            cfg.set_main_option('script_location', str(Path(database.__file__).parent / 'migrations'))
            with engine.begin() as connection:
                cfg.attributes['connection'] = connection
                command.upgrade(cfg, '0009')
                connection.exec_driver_sql("INSERT INTO categories (id,name,active,created_at) VALUES ('keep','Existing',1,'2026-09-30')")
                connection.exec_driver_sql('ALTER TABLE flow_plans ADD COLUMN research_run_id VARCHAR')
                connection.exec_driver_sql("ALTER TABLE flow_plans ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '[]'")
                connection.exec_driver_sql("ALTER TABLE flow_plans ADD COLUMN research_web BOOLEAN NOT NULL DEFAULT '0'")
            with patch.object(database, 'DB_PATH', path), patch.object(database, 'engine', engine):
                database.migrate()
                with sqlite3.connect(path) as connection:
                    self.assertEqual(connection.execute('SELECT version_num FROM alembic_version').fetchone()[0], '0010')
                    self.assertEqual(connection.execute("SELECT name FROM categories WHERE id='keep'").fetchone()[0], 'Existing')
                    columns = {row[1] for row in connection.execute('PRAGMA table_info(flow_plans)')}
                    self.assertTrue({'research_run_id','evidence_json','source_ids_json','artifact_ids_json',
                                     'resource_ids_json','research_candidates_json','research_web'} <= columns)
                def broken(config, _revision):
                    config.attributes['connection'].exec_driver_sql('CREATE TABLE migration_atomicity_probe (id INTEGER)')
                    raise RuntimeError('simulated migration failure')
                with patch('alembic.command.upgrade', side_effect=broken):
                    with self.assertRaisesRegex(RuntimeError, 'simulated migration failure'):
                        database.migrate()
                with sqlite3.connect(path) as connection:
                    self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='migration_atomicity_probe'").fetchone())
                    self.assertEqual(connection.execute('SELECT version_num FROM alembic_version').fetchone()[0], '0010')
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
