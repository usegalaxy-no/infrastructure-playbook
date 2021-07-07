#!/bin/bash

/bin/systemctl restart rabbitmq-server.service
/bin/systemctl start httpd.service