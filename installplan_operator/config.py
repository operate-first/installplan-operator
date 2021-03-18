from decouple import config
from pathlib import Path

# True if update_approver should approve updates, False to run in
# dry-run mode (check for updates but make no changes).
approve_updates = config('IPO_APPROVE_UPDATES', default='false', cast=bool)

# Where to look for update configuration files.
config_dir = config('IPO_CONFIG_DIR', default='/subscriptions', cast=Path)

# Set log level.
log_level = config('IPO_LOG_LEVEL', default='INFO')

# Run processing loop at least once every max_interval seconds.
max_interval = config('IPO_MAX_INTERVAL', default=900, cast=int)

# Ignore triggers if the last loop run was less than min_interval
# seconds ago.
min_interval = config('IPO_MIN_INTERVAL', default=10, cast=int)

# Produce color logs on stderr if True, otherwise do not use color.
colorize_logs = config('IPO_COLORIZE_LOGS', default=False, cast=bool)
