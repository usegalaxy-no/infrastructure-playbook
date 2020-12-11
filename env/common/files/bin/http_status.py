#!/usr/bin/env python3
"""



 Kim Brugger (25 Sep 2020), contact: kim@brugger.dk
"""
import argparse
import sys
import re
import json
import requests


def get_state(service) -> int:

    r = requests.get(service)
    return {'code':r.status_code, 'response_time':r.elapsed.total_seconds()}


def main():
    parser = argparse.ArgumentParser(description='systemd service status reporter')

    parser.add_argument('-t', '--telegraf', default=False, action="store_true",    help="telegraf compatible format")
    parser.add_argument('-j', '--json', default=False, action="store_true",    help="telegraf compatible format")
    parser.add_argument('-n', '--name',  help="service name (otherwise hostname)")
    parser.add_argument('services', nargs='*', help="service(s) to check (use pattern name=http:// to substitute hostname)")

    args = parser.parse_args()

    if len(args.services) == 0:
        print("No service(s) provided to check!")
        sys.exit(1)

    if len(args.services) >1 and args.name is not None:
        print("Cannot substitute service name when probing multiple services")
        sys.exit(1)


    statuses = []

    for service in args.services:
        #set the service name
        m = re.match(r'(.*?)=(.*?//.*)', service)
        if args.name is not None:
            name = args.name
        elif m:
            name, service = m.groups()
        else:
            name =re.sub(r'^.*?//', '', service)
            name =re.sub(r'(.*?)/.*$', r'\1', name)

        status = get_state(service)

        if args.telegraf:
            line = f"service,http_service={name} status_code={status['code']},response_time={status['response_time']}"
            print( line )
        else:
            status['name'] = name
            statuses.append( status )


    if args.json:
        print(json.dumps( statuses))
    elif not args.telegraf:

        print(f"{'name':20}\tcode\tresponse_time")
        print(f"--------------------------------------")
        for status in statuses:
            print(f"{status['name']:20}\t{status['code']}\t{status['response_time']}")



if __name__ == "__main__":
    main()
