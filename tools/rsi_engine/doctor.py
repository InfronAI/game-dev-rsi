"""Check the common runtime; delegate domain dependencies to a case-owned preflight."""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from .contracts import case_contract, read, relative, require


def diagnose(case_dir):
    case_dir = Path(case_dir).resolve()
    case, _, _ = case_contract(case_dir)
    environment = read(relative(case_dir, case['environment']))
    checks = [{'name': 'case', 'ok': True, 'detail': case['id']},
              {'name': 'python', 'ok': sys.version_info >= (3, 9), 'detail': sys.version.split()[0]}]
    substitutions = {'python': sys.executable, 'case_dir': str(case_dir)}
    if 'argv' in case['simulation']:
        executable = case['simulation']['argv'][0].format_map(substitutions)
        checks.append({'name': 'local_simulator', 'ok': bool(shutil.which(executable)), 'detail': executable})
    if environment.get('preflight'):
        spec = environment['preflight']
        try:
            proc = subprocess.run([a.format_map(substitutions) for a in spec['argv']], cwd=case_dir,
                                  capture_output=True, text=True, timeout=spec['timeout_seconds'])
            result = json.loads(proc.stdout)
            require(isinstance(result['checks'], list) and result['checks'], 'preflight needs checks')
            require(all(isinstance(c.get('ok'), bool) and c.get('name') for c in result['checks']), 'invalid preflight check')
            checks.extend(result['checks'])
            if proc.returncode:
                checks.append({'name': 'case_preflight_exit', 'ok': False, 'detail': proc.returncode})
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as e:
            checks.append({'name': 'case_preflight', 'ok': False, 'detail': str(e)})
    return {'ready': all(c['ok'] for c in checks), 'checks': checks,
            'scope': 'Local dependency checks only. Domain requirements come from the case.'}
