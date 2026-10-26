const args = [];
if (process.env.CASE_START_DATE) args.push('--start-date', process.env.CASE_START_DATE);
if (process.env.CASE_OUTPUT_DIR) args.push('--output-dir', process.env.CASE_OUTPUT_DIR);
if (process.env.CASE_MIN_DISK_MIB) args.push('--min-disk-mib', process.env.CASE_MIN_DISK_MIB);

module.exports = {
  apps: [{
    name: 'case-scraper-daily',
    cwd: __dirname,
    script: 'scrape_daily.py',
    interpreter: process.env.CASE_PYTHON || 'python3',
    args,
    instances: 1,
    exec_mode: 'fork',
    autorestart: false,
    watch: false,
    kill_timeout: 30000,
    env: { PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
  }],
};
