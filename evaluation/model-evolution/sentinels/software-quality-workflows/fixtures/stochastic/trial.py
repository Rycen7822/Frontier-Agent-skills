from pathlib import Path

state = Path(__file__).with_name('trial-state.txt')
trial = int(state.read_text()) + 1
state.write_text(f'{trial}\n')
if trial < 3:
    print(f'TRIAL_{trial}_FAIL')
    raise SystemExit(1)
print('TRIAL_3_PASS')
