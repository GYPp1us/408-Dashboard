"""Rehearse index settings initialization on a read-only online backup."""
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
import json
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.db import FOCUS_EXCHANGE_EFFECTIVE_KEY,init_db
from scripts.validate_checkin_upgrade import fingerprints

ALLOWED_SETTINGS={FOCUS_EXCHANGE_EFFECTIVE_KEY,'focus_kline_support_percent',
                  'focus_kline_resistance_percent','focus_kline_switch_minutes'}


def rehearse(database,copy):
    if copy.exists() or database.resolve()==copy.resolve():
        raise ValueError('Use a new, separate rehearsal database')
    source=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
    target=sqlite3.connect(copy)
    try:
        source.backup(target)
        target.row_factory=sqlite3.Row
        before=fingerprints(target)
        original_settings=dict(target.execute('SELECT key,value FROM settings'))
        init_db(target)
        current_settings=dict(target.execute('SELECT key,value FROM settings'))
        added=set(current_settings)-set(original_settings)
        assert added<=ALLOWED_SETTINGS, 'Unexpected new settings'
        assert all(current_settings[k]==v for k,v in original_settings.items()), 'Existing settings changed'
        assert datetime.fromisoformat(current_settings[FOCUS_EXCHANGE_EFFECTIVE_KEY]).tzinfo is not None
        assert {'checkin_rules','checkin_records','checkin_reporter_keys'}<=set(before)
        assert target.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert target.execute('PRAGMA foreign_key_check').fetchall()==[]
        # Compare every pre-existing row after omitting only permitted inserts.
        # This temporary deletion is confined to the disposable rehearsal copy.
        target.executemany('DELETE FROM settings WHERE key=?',[(key,) for key in added])
        after=fingerprints(target)
        assert after==before, 'Pre-existing data changed'
        target.rollback()
        return {'passed':True,'unchangedTables':len(before),'addedSettings':sorted(added),
                'quickCheck':'ok','foreignKeyViolations':0,'sourceOpenedReadOnly':True}
    finally:
        source.close()
        target.close()


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('database',type=Path)
    parser.add_argument('copy',type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    result=rehearse(args.database,args.copy)
    text=json.dumps(result,indent=2)
    if args.report:
        args.report.write_text(text+'\n',encoding='utf-8')
    print(text)
