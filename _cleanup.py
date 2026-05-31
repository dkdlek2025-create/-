import sqlite3, sys
c = sqlite3.connect('data/stock_agent.db')
c.execute("UPDATE scans SET status='finished', finished_at=datetime('now') WHERE status='running'")
c.commit()
print('cleaned', c.total_changes)
c.close()
sys.exit(0)
