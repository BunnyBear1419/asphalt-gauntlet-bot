from pathlib import Path
import ast

BOT = Path(__file__).resolve().parents[1] / 'main.py'
s = BOT.read_text(encoding='utf-8')
ast.parse(s)
required = {
    'MongoDB transaction': 'start_transaction()' in s and 'start_session()' in s,
    'Database backups': 'create_database_backup' in s and 'backup_loop' in s,
    'Manual backup command': 'name="backup"' in s,
    'Season archive storage': '"standings": archive_rows' in s,
    'Season archive command': 'name="seasonhistory"' in s,
    'Admin error alerts': 'send_admin_alert' in s and 'on_app_command_error' in s,
    'Database audit': 'name="dbcheck"' in s,
    'Deterministic match settlement': 'settlement_id' in s and 'settlement_status' in s,
}
failed = [k for k,v in required.items() if not v]
print(f'Checks passed: {len(required)-len(failed)}/{len(required)}')
for k,v in required.items(): print(('PASS' if v else 'FAIL') + ' - ' + k)
if failed: raise SystemExit(1)
