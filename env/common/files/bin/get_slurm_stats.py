# This script runs a few Slurm commands to gather information about nodes and the jobs running on them.
# The results are formatted as JSON and output to STDOUT.
# A few assumptions are made which must be taken into account if the script is to be used in other settings, including:
#  - Nodes have names on the format "*.usegalaxy.no" or "*.test.usegalaxy.no", and a list of nodes is never longer than 100 characters long
#  - The number of cores on each node does not exceed double digits
#  - Jobs are run by the "galaxy" OS user

import subprocess
import json
import re
import time
import datetime
import sys
import os
import signal


command_sacct  = "sacct -u galaxy -X --format=JobID,JobName%60,Start,End,Elapsed,AllocCPUS,ReqMem,State,NodeList%100"
command_sinfo  = ["sinfo","-N","-O","NodeList:30,StateLong,CPUsState,CPUsLoad,Memory,AllocMem,Weight,Reason:40"]
command_squeue = ["squeue","-o","%i %j %T %S %C %m %M %N %r"]
command_pids   = ["ssh","*","scontrol listpids; ps -u galaxy"] # nodename in second position will be inserted later
command_done   = "sacct -u galaxy -X --starttime XXX --format=JobID,End,State,NodeList%100" # starttime is replaced later

time_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
week_ago = datetime.datetime.now()-datetime.timedelta(days=7)
week_ago = (str(week_ago))[0:10]
command_done = command_done.replace('XXX',week_ago)

nodes = {}
response = {}
pending = []
completing = {} # key is slurm_ID
completed= {} # key is node name

def time_difference(time1,time2):
    time1=str(time1)
    time2=str(time2)
    d1 = datetime.datetime.strptime(time1[0:10], "%Y-%m-%d")
    d2 = datetime.datetime.strptime(time2[0:10], "%Y-%m-%d")
    diff = str(d1-d2)
    if (diff=="0:00:00" or diff=="00:00:00"):
        return 0
    else:
        days = int(diff.split(" ")[0])
        return days

# Given a list of text lines, this function will split the lines into two lists
# with the second list starting at the line matching the provided regex-pattern
def split_command_output(lines, pattern):
    for index, line in enumerate(lines):
        if (re.match(pattern, line)):
            first_part = lines[0:index]
            second_part = lines[index:]
            return first_part, second_part
    raise Exception("Unable to split input")

# replaces a list or comma-separated string of long nodenames with their short counterparts
def shorten_nodenames(nodelist):
   if (isinstance(nodelist, list)):
       newlist = []
       for nodename in nodelist:
           newlist.append(nodes[nodename]['shortname'] if (nodename in nodes) else nodename)
       return newlist
   else:
       newlist = []
       for nodename in nodelist.split(','):
           newlist.append(nodes[nodename]['shortname'] if (nodename in nodes) else nodename)
       return ",".join(newlist)
       
# run a shell command with timeout
def run_command(command, timeout=10):
    with subprocess.Popen(command, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, preexec_fn=os.setsid) as process:
        try:
            output = process.communicate(timeout=timeout)[0]
            return output.splitlines()
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGINT) # send kill signal to the process group
            output = process.communicate()[0]
            return output.splitlines()
        except Exception:
            output = process.communicate()[0]
            return output.splitlines()


# ------------------------------------------------------------------------------------------------------------------


# --- SINFO ---
try:
    result = run_command(command_sinfo, timeout=5)
    for line in result[1:]: # skip header
        columns = re.split('\s+', line.decode("utf-8").strip(), 7) # don't split the last column because "reason" can contain spaces
        nodename = columns[0]
        shortname = re.split('\.',nodename)[0]
        responding = True
        state = columns[1]
        if (state.endswith('*')):
            state = state[0:-1]
            responding = False
        cpus_state = columns[2].split('/')
        cpus_used  = int(cpus_state[0])
        cpus_total = int(cpus_state[3])
        memory_used  = int(columns[5])
        memory_total = int(columns[4])
        weight = int(columns[6])
        reason = columns[7]
        node = { 'name':nodename, 'state':state, 'responding':responding, 'cpus':cpus_total, 'memory':memory_total, 'weight':weight, 'reason':reason }
        node['shortname'] = shortname
        node['memory_gb'] = f"{int(memory_total/1024)}"
        node['cpus_used'] = cpus_used
        node['memory_used'] = memory_used         
        node['memory_used_gb'] = f"{int(memory_used/1024)}"
        node['running_jobs'] = 0
        node['jobs'] = []
        nodes[nodename] = node
except Exception as error:
    response['error']=str(error)
    #raise error


# --- SQUEUE --- Get information about completing and pending jobs also
try:
    result =  run_command(command_squeue, timeout=5)
    for line in result[1:]: # skip header
        columns = re.split('\s+', line.decode("utf-8").strip(),8)
        galaxy_job = re.split('_',columns[1],1)
        toolname = galaxy_job[1]
        galaxy_jobid = int(galaxy_job[0][1:])
        slurm_jobid = int(columns[0])
        state  = columns[2]
        start  = columns[3]
        cpus   = int(columns[4])
        memory = columns[5]
        elapsed= columns[6]
        if (len(columns)>8):
            node = columns[7] # This could be a comma-separated list, but that is OK for now
            reason = columns[8]
        else:
            reason = columns[7]
        memory = int(columns[5][:-1])
        memory_unit = columns[5][-1:]          
        if (memory_unit == 'G'):
            memory_display = f"{memory}GB"
            memory = memory * 1024
        elif (memory_unit == 'M'):
            memory_display = f"{memory}MB"
        else:
            raise Exception(f"Unable to parse memory unit from 'squeue': {memory_unit}")
        if (state == "PENDING"):
            job = { 'tool':toolname, 'cpus':cpus, 'state':'pending', 'reason':reason,
                    'galaxy_jobid':galaxy_jobid, 'slurm_jobid':slurm_jobid, 'memory':memory, 'memory_display':memory_display }
            pending.append(job)
        elif (state == "COMPLETING"):
            job = { 'tool':toolname, 'cpus':cpus, 'state':'completing', 'start':start, 'elapsed':elapsed, 'nodename':node,
                    'galaxy_jobid':galaxy_jobid, 'slurm_jobid':slurm_jobid, 'memory':memory, 'memory_display':memory_display }
            completing[slurm_jobid] = job
except Exception as error:
    response['error']=str(error)
    #raise error


# --- SACCT ---
try:
    result = run_command(command_sacct.split(), timeout=5)
    for line in result[2:]: # skip header. First line contains column names, second line is a border
        columns = re.split('\s+', line.decode("utf-8").strip())
        state = columns[7]
        is_cancelled = state.startswith('CANCELLED')
        if (state=='RUNNING' or state=='COMPLETING' or is_cancelled): # Not sure if COMPLETING is a possible state   
            galaxy_job = re.split('_',columns[1],1)
            toolname = galaxy_job[1]
            galaxy_jobid = int(galaxy_job[0][1:])
            slurm_jobid = int(columns[0])
            if (is_cancelled and not (slurm_jobid in completing)): 
                continue
            if (is_cancelled and slurm_jobid in completing): # this may still be taking up resources on the node
                state = "COMPLETING" # "Completing (CANCELLED)"
                del completing[slurm_jobid]
            nodename = columns[8] # this may be a comma-separated list!
            memory = int(columns[6][:-2])
            memory_unit = columns[6][-2:] # should be either Gn or Mn (or Gc/Mc)
            if (memory_unit == 'Gn'):
                memory_display = f"{memory}GB"
                memory = memory * 1024
            elif (memory_unit == 'Gc'):
                cpus = int(columns[5])
                memory = memory * 1024 * cpus
                memory_display = f"{memory}GB"
            elif (memory_unit == 'Mn'):
                memory_display = f"{memory}MB"
            elif (memory_unit == 'Mc'):
                cpus = int(columns[5])
                memory = memory * cpus
                memory_display = f"{memory}MB"
            else: 
                raise Exception(f"Unable to parse memory unit from 'sacct': {memory_unit}")
            job = { 'tool':toolname, 'start':columns[2], 'elapsed':columns[4], 'cpus':int(columns[5]), 'state':state, 'cancelled':is_cancelled,
                    'galaxy_jobid':galaxy_jobid, 'slurm_jobid':slurm_jobid, 'memory':memory, 'memory_display':memory_display }
            # update allocated CPUs and memory on each node based on the jobs running on them => Not necessary! I got this info elsewhere! 
            if (nodename in nodes):
                node = nodes[nodename]
                node['jobs'].append(job)
                node['running_jobs'] = node['running_jobs']+1
#                node['memory_used'] = node['memory_used']+job['memory']
#                memory_used_gb = round(node['memory_used']/1024)
#                node['memory_used_gb'] = f"{memory_used_gb}"
#                node['cpus_used'] = node['cpus_used']+job['cpus']
            elif (',' in nodename):
                nodelist = nodename.split(',')
                job['split_across'] = shorten_nodenames(nodelist)                     
                for node_name in nodelist:
                    if (node_name not in nodes):
                        raise Exception(f"Nodename '{node_name}' not recognized")
                    node = nodes[node_name]
                    node['jobs'].append(job) # NB! If the job is split across nodes, the number of cores and memory is also split!! But how?!
                    node['running_jobs'] = node['running_jobs']+1
            else:
                raise Exception(f"Nodename '{nodename}' not recognized")
except Exception as error:
    response['error'] = str(error)    
    #raise error

# Now add the jobs that where reported as COMPLETING by 'squeue' but not included by 'sacct'
# => I'm not sure if this is needed anymore...
# -------------------
#for jobid, job in completing.items():
#    nodename = job['nodename']
#    if (nodename in nodes):
#        node = nodes[nodename]
#        node['memory_used'] = node['memory_used']+job['memory']
#        memory_used_gb = round(node['memory_used']/1024)
#        node['memory_used_gb'] = f"{memory_used_gb}"
#        node['cpus_used'] = node['cpus_used']+job['cpus']
#        node['jobs'].append(job)
#        node['running_jobs'] = node['running_jobs']+1
#    else:
#        raise Exception(f"Nodename '{nodename}' not recognized")


# --- SACCT for jobs in last 7 days ---
count_days = 7
for nodename in nodes:
    # The "completed" datastructure counts the number of jobs that were completed on a given node in the last X days.
    # The index is number of days ago. First index is today, second is yesterday, etc. 
    # The value is the number of jobs completed on that day.
    completed[nodename] = [0]*count_days
try:
    result = run_command(command_done.split(), timeout=5)
    for line in result[2:]: # skip header. First line contains column names, second line is a border
        columns = re.split('\s+', line.decode("utf-8").strip())
        if (columns[2]=="COMPLETED"):
            timestamp = columns[1]
            days_ago = time_difference(time_now, timestamp)
            if (days_ago < 0 or days_ago >= count_days):
                continue
            nodename = columns[3]
            if (',' in nodename):
                for n in nodename.split(','):
                    if (nodename in completed):
                        completed[n][days_ago]+=1
            else:
                if (nodename in completed):
                    completed[nodename][days_ago]+=1
except Exception as error:
    response['error'] = str(error)
    raise error


# --- scontrol listpids + ps -u galaxy ---
# Check if the jobs have corresponding processes running on the compute nodes
# A 'pid' attribute will be added to each job in a node's 'jobs' list.
# This attribute could either be a list or a numeric value. 
# If the value is 0, it means that information is missing for this job. This could just be a temporary issue.
# If the value is -1, it explicitly means that the Slurm job does not have a corresponding process on the compute node. This is bad!
# If the value is a list, it is a list of [pid,cmd] pairs with information about each process associated with the slurm job.  
for nodename,node in nodes.items():
    if (node['jobs']):
        command_pids[1] = nodename
        process_commands = {} # mapping between PID and process command (from "ps")
        pids = {} # Mapping between Slurm job ID and local processes. Note that a slurm job can have multiple processes, so the value is a list
        try:
            result = run_command(command_pids, timeout=8)
            for index, line in enumerate(result):
                result[index] = line.decode("utf-8").strip() # convert to regular text
            listpids, ps_galaxy = split_command_output(result, '\s*PID\s+TTY\s+TIME\s+CMD\s*') # separate output from "listpids" and "ps"
            if (len(listpids)==2 and listpids[1]=="No job steps exist on this node."):
                pass
            else:                
                for line in ps_galaxy[1:]: # skip header
                    columns = re.split('\s+', line)
                    pid = int(columns[0])
                    cmd = columns[-1]
                    process_commands[pid] = cmd
                for line in listpids[1:]: # skip header
                    columns = re.split('\s+', line)
                    if (len(columns)==5):
                        slurm_job = int(columns[1])
                        pid = int(columns[0])
                        if (pid == -1):
                            pids[slurm_job] = -1  # local process is missing for this jobs. Report this as an empty list
                        else:
                            if (slurm_job not in pids):
                                pids[slurm_job] = []
                            cmd = process_commands[pid] if (pid in process_commands) else "*** Missing command ***"
                            pids[slurm_job].append( [pid,cmd] ) 
            for job in node['jobs']:
                slurm_id = job['slurm_jobid']
                job['pid'] = pids[slurm_id] if (slurm_id in pids) else 0                         
        except Exception as error:
            pass
            #print("Unable to get Slurm PIDs for Slurm jobs on [%s]: %s" % (node['name'],str(error)),file=sys.stderr)

if ('error' not in response):
    response['nodes'] = list(nodes.values())
    if (len(pending)>0):
        response['pending'] = pending
    response['completed'] = completed
    response['time'] = time.time()
    response['display_time'] = time_now

json_doc = json.dumps(response, indent=4)
print(json_doc)
