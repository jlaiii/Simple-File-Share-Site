#!/usr/bin/env python3
import os
import sys
import argparse
import platform
import subprocess
import venv

def create_venv(path):
    if os.path.isdir(path) and os.path.exists(get_venv_python(path)):
        print(f"Virtualenv already exists at {path}")
        return
    print(f"Creating virtualenv at {path}...")
    venv.EnvBuilder(with_pip=True).create(path)

def get_venv_python(path):
    if platform.system() == 'Windows':
        return os.path.join(path, 'Scripts', 'python.exe')
    return os.path.join(path, 'bin', 'python')

def install_requirements(python_exe, req='requirements.txt'):
    if not os.path.exists(req):
        print('No requirements.txt found — skipping install')
        return
    print('Installing requirements...')
    subprocess.check_call([python_exe, '-m', 'pip', 'install', '--upgrade', 'pip'])
    subprocess.check_call([python_exe, '-m', 'pip', 'install', '-r', req])

def run_main(python_exe, host, port, extra_args):
    cmd = [python_exe, 'main.py', '--host', host, '--port', str(port)] + extra_args
    print('Starting app: ' + ' '.join(cmd))
    # Replace current process with the venv python running main.py where possible
    try:
        os.execv(python_exe, cmd)
    except AttributeError:
        # fallback for platforms where execv may not behave as expected
        subprocess.check_call(cmd)

def main():
    p = argparse.ArgumentParser(description='Create venv, install deps, and run main.py')
    p.add_argument('--venv', default='venv', help='venv directory')
    p.add_argument('--no-install', action='store_true', help='skip installing requirements')
    p.add_argument('--host', default='0.0.0.0', help='host to bind')
    p.add_argument('--port', type=int, default=3109, help='port to bind')
    p.add_argument('extra', nargs=argparse.REMAINDER, help='extra args passed to main.py')
    args = p.parse_args()

    venv_path = args.venv
    create_venv(venv_path)
    py = get_venv_python(venv_path)
    if not os.path.exists(py):
        print('ERROR: venv python not found at', py)
        sys.exit(2)

    if not args.no_install:
        try:
            install_requirements(py)
        except subprocess.CalledProcessError:
            print('Failed to install requirements')
            sys.exit(3)

    run_main(py, args.host, args.port, args.extra)

if __name__ == '__main__':
    main()
