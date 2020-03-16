#!/usr/bin/env python3
""" 
 
 Kim Brugger (03 Apr 2019), contact: kim@brugger.dk
"""

import sys
import argparse
import pprint
pp = pprint.PrettyPrinter(indent=4)

import pika

connection = None
channel    = None


def connect(uri:str, ):
  global connection
  global channel

  connection = pika.BlockingConnection( pika.connection.URLParameters(uri) )
  channel    = connection.channel()


def main():

  parser = argparse.ArgumentParser(description='get-workflows: export workflows from a galaxy instance ')
  parser.add_argument('-u', '--url', required=True, help="uri to connect to, eg: amqp://user:password@host:port/vhost")


  args = parser.parse_args()
  url = args.url

  connect( url )


main()
