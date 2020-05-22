#!/usr/bin/python3
import time
import re
import subprocess
import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)


#logger.setLevel(logging.DEBUG)


def run(cmd, test_mode=False, ignore_errors=False):
    logger.debug('run: {0}'.format(cmd))
    if test_mode:
        return 'skipped'
    retry = 0
    while True:
        # run under bash and try and load /etc/prodfile.d/* so slurm bins are in path.
        p = subprocess.run('source /etc/profile; {0}'.format(cmd), encoding='utf-8', shell=True,
                           executable='/bin/bash', timeout=5, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.stderr:
            # try to hide errors.
            logger.debug(p.stderr)
        logger.debug(p.stdout)
        if p.returncode:
            if ignore_errors:
                return None
            if 'slurm_persist_conn_open' in p.stderr:
                retry = retry + 1
                if retry > 2:
                    raise Exception('After some retries - dbconnections timeout')
                logger.debug('sleeping 5 seconds to let dbconnections timeout')
                time.sleep(5)
                continue
            raise Exception('stderr: {0}'.format(p.stderr))
        stdout = p.stdout
        break
    return stdout


def parse_slurm_list(cmd, valid_prop=[], regex_filter={}, skip_lines=0):
    '''
    split headers and values into dict.
    the split delimiter is bar'|'

    cmd: shell command
    valid_prop: props to be returned for each line item
    regex_filter: filter items that header: value match.
    '''
    raw = run(cmd)
    raw = raw.split('\n')
    raw = raw[skip_lines:]
    header = raw[0].lower().split('|')
    out = {}
    for l in raw[1:-1]:
        d = l.split('|')
        props = {}
        filtered = False
        for i, h in enumerate(header):
            if not valid_prop or h in valid_prop:
                props[h] = d[i]
            if h in regex_filter:
                if not re.match(regex_filter[h], d[i]):
                    filtered = True
                    break
        if not filtered:
            out[d[0]] = props
    return out


# get cluster list
cmd = "sacctmgr list cluster --parsable2"
clusters = parse_slurm_list(cmd, [])



#---- slurm nodes
# sinfo --clusters='hpc-co1' -o '%n|%T|%e|%d|%O'
# --noconvert
for c in clusters:
    try:
        data = parse_slurm_list("sinfo '--clusters={0}' -o '%n|%T|%e|%d|%O'".format(c), skip_lines=1)
    except:
        continue
    logger.debug(data)
    for h in data:
        metric = 'slurm_node,cluster={1},node={2[hostnames]},state={2[state]} free_mem={2[free_mem]},tmp_disk={2[tmp_disk]},cpu_load={2[cpu_load]} '
        metric = metric.format('', c, data[h])
        metric = metric.replace('N/A', '0').replace('*', '')
        print(metric)



'''
#---- slurm partitions
## TODO: how busy is partition?
for c in clusters:
    try:
        data = parse_slurm_list("sinfo '--clusters={0}' -o '%R|%n|%T|%e|%d|%O'".format(c), skip_lines=1)
    except:
        continue
    logger.debug(data)
    for h in data:
        print('slurm_partition,cluster={1},partition={2[partition]},node={2[hostnames]},state={2[state]} free_mem={2[free_mem]},tmp_disk={2[tmp_disk]},cpu_load={2[cpu_load]} '.format('', c, data[h]))
'''


#---- slurm scheduler
# sdiag
out = run('sdiag')
tag_re = {
    'server_thread_count': re.compile('Server thread count:(.*)'),
    'agent_queue_size': re.compile('Agent queue size:(.*)'),
    'dbd_agent_queue_size': re.compile('DBD Agent queue size:(.*)'),
    'jobs_submitted': re.compile('Jobs submitted:(.*)'),
    'jobs_started': re.compile('Jobs started:(.*)'),
    'jobs_completed': re.compile('Jobs completed:(.*)'),
    'jobs_canceled': re.compile('Jobs canceled:(.*)'),
    'jobs_failed': re.compile('Jobs failed:(.*)'),
    'jobs_running': re.compile('Jobs running:(.*)'),
    'last_cycle': re.compile('Last cycle:(.*)'),
    'total_cycle': re.compile('Total cycles:(.*)'),
    'mean_cycle': re.compile('Mean cycle:(.*)'),
    'mean_depth_cycle': re.compile('Mean depth cycle:(.*)'),
    'cycles_per_minute': re.compile('Cycles per minute:(.*)'),
    'backfilling_total_cycle': re.compile('Backfilling stats[\S\s]*?Total cycles:(.*)'),
    'backfilling_last_cycle': re.compile('Backfilling stats[\S\s]*?Last cycle:(.*)'),
    'backfilling_last_depth_cycle': re.compile('Backfilling stats[\S\s]*?Last depth cycle:(.*)'),
}
values = []
for t in tag_re:
    m = tag_re[t].search(out)
    values.append('{0}={1}'.format(t, int(m.group(1))))
metric = 'slurm_scheduler {0}'.format(','.join(values))
metric = metric.replace('N/A', '0').replace('*', '')
print(metric)
