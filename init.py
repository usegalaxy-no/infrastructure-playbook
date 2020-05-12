#!/usr/bin/env python3

import subprocess
import sys
import os

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def launch_cmd(cmd: str):

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True, stderr=subprocess.PIPE,
                         )

    stdout, stderr = p.communicate()
    p_status = p.wait()
    if stderr and stderr != '':
        print(bcolors.WARNING + stdout.decode("utf-8"))

    if stdout and stdout != b'' and stdout != stderr :
        print(f"{bcolors.OKGREEN} {stdout}")


def virtual_env_init() -> None:

    if os.path.isdir('venv'):
        print('venv already exits, skipping virtualenv init')

    print(bcolors.OKBLUE +'virtual env init')
    cmd = 'python3 -m venv venv'
    launch_cmd( cmd )


def install_python_deps() -> None:

    cmd = './venv/bin/pip install -r requirements.txt'
    print(bcolors.OKBLUE +'install python packages')
    launch_cmd( cmd )


def install_ansible_deps() -> None:
    cmd = './venv/bin/ansible-galaxy install -p env/common/roles/ -r env/common/requirements.yml'
    print(bcolors.OKBLUE +'install ansible roles')
    launch_cmd( cmd )



def main() -> None:


    virtual_env_init()
    install_python_deps()
    install_ansible_deps()

    print( 'to use virtual environment: source venv/bin/activate')

if __name__ == '__main__':
    main()
