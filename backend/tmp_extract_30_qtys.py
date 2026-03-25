import json
from pathlib import Path
rep = json.loads(Path('LIVE_AUTO_ESCALATION_30_QUANTITY_ONLY_REPORT.json').read_text(encoding='utf-8'))
qtys = [int(round(float(r.get('requested_quantity') or 0))) for r in rep.get('requests', [])]
print('QTY_COUNT', len(qtys))
print('QTY_LIST', qtys)
print('WAVES', rep.get('waves'))
