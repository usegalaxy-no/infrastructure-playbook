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
exchange   = None
channels   = []


def connect(uri:str, exchange:str='default', exchange_type:str='direct'):
  global connection
  global channel
  global exchange
  
  connection = pika.BlockingConnection( pika.connection.URLParameters(uri) )
  channel    = connection.channel()
  exchange   = exchange
  
  channel.exchange_declare(exchange=exchange, exchange_type=exchange_type, durable=True)



def _check_channel(name:str):
  if name not in channels:
    
    result = channel.queue_declare(queue=name, durable=True)
    
    channel.queue_bind(exchange=exchange,
                       queue=name,
                       routing_key=name)
    global channels
    channels.append( name )
            
def publish(body:str, route:str='default'):

  _check_channel( route)
  channel.basic_publish( exchange=exchange, routing_key=route, body=body, properties=pika.BasicProperties( delivery_mode=2))
        
def consume(route:str='default', callback=None):
  try:
    _check_channel( route)
    channel.basic_consume(queue=route, on_message_callback=callback)
    channel.start_consuming()
  except Exception as e:
    print( e )


def queue_length(queue:str=None):
  result = channel.queue_declare(queue=queue, durable=True, passive=True)
  return result.method.message_count
    


def main():

  parser = argparse.ArgumentParser(description='get-workflows: export workflows from a galaxy instance ')
  parser.add_argument('-u', '--url', required=True, help="uri to connect to, eg: amqp://user:password@host:port/vhost")


  args = parser.parse_args()
  url = args.url

  connect( url )
  publish(body="Test publish to the queue")

main()
