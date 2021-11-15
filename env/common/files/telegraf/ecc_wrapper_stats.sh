#!/bin/bash

cd /srv/ecc

/srv/ecc/venv/bin/python /srv/ecc/bin/ecc-cli list | cut -d '|' -f 5 \
                         | grep -v "+-" | grep -v 'vm-state' | egrep -v '^[ \t\n]*$' \
                         | uniq -c \
                         | awk '{ printf "ecc_status,status=%s count=%s\n",$2,$1 }'

