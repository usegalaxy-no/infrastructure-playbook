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
exchange   = ''
channels   = []


def connect(uri:str, exchange_type:str='direct'):
  global connection
  global channel

  connection = pika.BlockingConnection( pika.connection.URLParameters(uri) )
  channel    = connection.channel()


def publish(body:str, route:str='default'):

  channel.basic_publish( exchange=exchange, routing_key=route, body=body, properties=pika.BasicProperties( delivery_mode=2))
  print("Written {}".format( body ))

def callback(ch, method, properties, body):
  print(" [x] Received {}".format(body))
  ch.basic_ack(delivery_tag=method.delivery_tag)


def consume(route:str='default', callback=None):
  try:
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=route, on_message_callback=callback)
    channel.start_consuming()
  except Exception as e:
    print( e )



def main():

  parser = argparse.ArgumentParser(description='get-workflows: export workflows from a galaxy instance ')
  parser.add_argument('-u', '--url', required=True, help="uri to connect to, eg: amqp://user:password@host:port/vhost")
  parser.add_argument('-w', '--write', action="store_true", help="write to vhost")
  parser.add_argument('-r', '--read', action="store_true", help="read from vhost")


  args = parser.parse_args()
  url = args.url

  connect( url )
  if args.write:
    publish(body="Test publish to the queue")

  if args.read:
    consume(callback=callback)


if __name__ == '__main__':

  main()

