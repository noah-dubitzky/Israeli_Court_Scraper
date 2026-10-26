const args = [
  '--resume', process.env.CASE_CHECKPOINT || 'output/pm2_cases.json',
  '--headless', '--non-interactive',
];
// For a new checkpoint, supply CASE_DATE (DD/MM/YYYY). Existing files supply
// their own date and case type, so these settings can be omitted on restart.
if (process.env.CASE_DATE) args.push('--date', process.env.CASE_DATE);
if (process.env.CASE_TYPE_ID) args.push('--case-type-id', process.env.CASE_TYPE_ID);

module.exports = {
  apps: [{
    name: 'case-scraper',
    cwd: __dirname,
    script: 'main.py',
    interpreter: process.env.CASE_PYTHON || 'python',
    args,
    instances: 1,
    exec_mode: 'fork',
    autorestart: true,
    restart_delay: 5000,
    stop_exit_codes: [0],
    watch: false,
    env: { PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
  }],
};
